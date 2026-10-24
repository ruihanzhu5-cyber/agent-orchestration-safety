"""Direct Docker backend. Model strings are never executed by a host shell."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import subprocess
import tarfile
import threading
import time
import uuid
from pathlib import Path

import yaml

from . import remote_worker
from .case_loader import materialize_case
from .common import BASE_IMAGE, BASE_IMAGE_ID, DynamicError, canonical, digest, write_json
from .events import EventLedger
from .operations import OperationStore
from .dependencies import fd_binary, fd_lock


class DockerEnvironment:
    def __init__(self, root: Path, *, branch_id: str | None = None, ledger: EventLedger | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = branch_id or uuid.uuid4().hex
        self.project = "tfv9-" + uuid.uuid4().hex[:16]
        self.label = "io.trustfork.dynamic.run=" + self.run_id
        self.ledger = ledger
        self.operations = OperationStore(self.root / "operations.sqlite")
        self.active = set()
        self.active_lock = threading.RLock()
        self.cancelled_operations = set()
        self.accepting = True
        self.frozen = False
        self.prepared = False
        self.closed = False
        self.container = None
        self.config_path = self.root / "compose.generated.yaml"
        config_dir = self.root / "docker-client"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "config.json").write_text("{}\n")
        self.client_env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "DOCKER_CONFIG": str(config_dir)}
        self.worker_source = Path(remote_worker.__file__).read_text()

    def docker(self, *args, timeout=60, binary=False, check=True):
        result = subprocess.run(["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", *map(str, args)],
                                env=self.client_env, capture_output=True, text=not binary, timeout=timeout)
        if check and result.returncode:
            error = result.stderr.decode(errors="replace") if binary else result.stderr
            raise DynamicError("docker_command_failed", error.strip(), evidence={"operation": args[0], "exit": result.returncode})
        return result

    def compose(self, *args, **kwargs):
        return self.docker("compose", "--project-name", self.project, "--file", self.config_path, *args, **kwargs)

    def prepare(self, case: dict) -> dict:
        if self.prepared:
            raise DynamicError("environment_already_prepared", self.run_id)
        inspected = json.loads(self.docker("image", "inspect", BASE_IMAGE).stdout)[0]
        if inspected["Id"] != BASE_IMAGE_ID:
            raise DynamicError("base_image_drift", "Audited image ID changed")
        self.case = copy.deepcopy(case)
        context = self.root / "context"
        manifest = materialize_case(case, context)
        original_compose = context / "docker-compose.yaml"
        source = yaml.safe_load(original_compose.read_text()) if original_compose.exists() else {"services": {"main": {}}}
        if source is None or set(source) - {"services", "networks"} or "main" not in source["services"]:
            raise DynamicError("unsupported_compose_shape", case["case_id"])
        self.compose_config = {"services": {}}
        for name, service in source["services"].items():
            if service.get("volumes") or service.get("privileged") or service.get("network_mode") == "host":
                raise DynamicError("unreviewed_service_isolation", name)
            if name != "main" and ("image" not in service or "build" in service):
                raise DynamicError("unresolved_service_image", name)
            self.compose_config["services"][name] = copy.deepcopy(service)
        image = "trustfork-case:" + case["case_id"] + "-" + manifest["generated_dockerfile_sha256"][:16]
        existing = self.docker("image", "inspect", image, check=False)
        if existing.returncode == 0:
            meta = json.loads(existing.stdout)[0]
            if (meta["Config"].get("Labels") or {}).get("io.trustfork.context") != digest(manifest):
                raise DynamicError("case_image_label_mismatch", image)
        else:
            build = self.docker("build", "--pull=false", "--progress=plain", "--label", "io.trustfork.context=" + digest(manifest),
                                "--tag", image, context, timeout=case.get("build_timeout_sec", 1200))
            (self.root / "image-build.log").write_text(build.stdout + build.stderr)
        main = self.compose_config["services"]["main"]
        main.pop("build", None)
        main.update(image=image, pull_policy="never", hostname="task",
                    cpus=case["resources"]["cpus"], mem_limit=f"{case['resources']['memory_mb']}m",
                    labels={"io.trustfork.dynamic.run": self.run_id}, init=True)
        main.setdefault("command", ["sleep", "infinity"])
        for service in self.compose_config["services"].values():
            service.setdefault("labels", {})["io.trustfork.dynamic.run"] = self.run_id
            service["pull_policy"] = "never"
        self.config_path.write_text(yaml.safe_dump(self.compose_config, sort_keys=True))
        self.compose("up", "--detach", "--no-build", "--pull", "never", timeout=120)
        self.container = self.compose("ps", "-q", "main").stdout.strip()
        if not self.container:
            raise DynamicError("missing_task_container", self.run_id)
        actual = json.loads(self.docker("inspect", self.container).stdout)[0]
        mounts = actual.get("Mounts", [])
        if mounts:
            raise DynamicError("unexpected_task_mount", "Task container must not mount control files or Docker socket", evidence=mounts)
        # The audited image lacks fd. Copy only this public, fixed-hash tool;
        # no control directory or mount is exposed to the task environment.
        self.docker('cp',fd_binary(),self.container+':'+fd_lock()['task_path'])
        self.docker('exec',self.container,'chmod','755',fd_lock()['task_path'])
        self.prepared = True
        self.start_services()
        self.baseline_processes = self._worker("process.snapshot", {}, "baseline-processes")["processes"]
        self.baseline_top = self._top()
        self.baseline_service_files = self._service_file_hashes()
        write_json(self.root / "environment-handle.json", {"run_id": self.run_id, "project": self.project,
                   "case_id": case["case_id"], "container": self.container, "base_id": BASE_IMAGE_ID,
                   "image_id": actual["Image"], "materialization": manifest, "mounts": mounts})
        return {"status": "prepared", "case_id": case["case_id"], "materialization": manifest}

    def _worker(self, operation: str, args: dict, op_id: str, *, timeout=60) -> dict:
        payload = base64.b64encode(canonical({"operation": operation, "args": args, "op_id": op_id})).decode()
        result = self.docker("exec", self.container, "python", "-c", self.worker_source, payload, timeout=timeout)
        try:
            body = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise DynamicError("invalid_operation_response", "Task operation did not return JSON") from error
        if not body["ok"]:
            raise DynamicError("remote_" + body["error_type"], body["message"], evidence={'errno':body.get('errno')})
        return body["result"]

    def start_services(self) -> dict:
        if not self.case["required_services"]:
            return {"status": "no_services"}
        # Probe the original service and original page; never substitute a fixture web server.
        script = "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/__list',timeout=2); print(r.read().decode())"
        last = None
        for _ in range(30):
            result = self.docker("exec", self.container, "python", "-c", script, check=False, timeout=5)
            if result.returncode == 0:
                health = json.loads(result.stdout)
                write_json(self.root / "service-health.json", health)
                return {"status": "running", "health": health}
            last = result.stderr[-1000:]
            time.sleep(0.1)
        raise DynamicError("service_not_ready", "Original mock API did not start", evidence=last)

    def exec_work_operation(self, operation: str, args: dict, op_id: str, *, scope=None) -> dict:
        if not self.accepting or self.frozen:
            raise DynamicError("environment_not_accepting", "No work after quiesce or freeze")
        claim = self.operations.claim(op_id, {"operation": operation, "args": args})
        if claim["cached"]:
            return claim["result"]
        with self.active_lock:
            self.active.add(op_id)
        if self.ledger:
            self.ledger.append("tool_operation_started", {"op_id": op_id, "operation": operation, "args": args}, tool_call_id=op_id, **(scope or {}))
        try:
            result = self._worker(operation, args, op_id, timeout=max(60, args.get("timeout", 0) + 10))
            stored = self.operations.finish(op_id, result)
            if self.ledger:
                self.ledger.append("tool_operation_finished", {"op_id": op_id, "result": result,
                    "observation_interval": [stored["started_ns"], stored["ended_ns"]],
                    "overlapping_operation_ids": stored["overlapping_operation_ids"],
                    "attribution_status": "ambiguous" if stored["overlapping_operation_ids"] else "single_recorded_operation"}, tool_call_id=op_id, **(scope or {}))
            return result
        except BaseException as error:
            if self.operations.get(op_id)["status"] == "started":
                self.operations.finish(op_id, {"error": type(error).__name__, "reason": str(error)}, unknown=True)
            raise
        finally:
            with self.active_lock:
                self.active.discard(op_id)

    def capture_observation(self, paths: list[str]) -> dict:
        if self.frozen:
            raise DynamicError("frozen_use_export", "Read frozen tar exports instead of exec")
        result = {}
        for path in paths:
            copied=self.docker('cp',self.container+':'+path,'-',binary=True,check=False)
            if copied.returncode:
                if b'could not find' in copied.stderr.lower() or b'no such' in copied.stderr.lower():
                    result[path]={'exists':False};continue
                raise DynamicError('observation_failed',path)
            with tarfile.open(fileobj=io.BytesIO(copied.stdout)) as archive:
                members=list(archive)
                if not members:raise DynamicError('empty_observation_archive',path)
                member=members[0]
                result[path]={'exists':True,'isDirectory':member.isdir(),'mode':member.mode,'type':member.type.decode(),'link':member.linkname}
                if member.isfile():
                    data=archive.extractfile(member).read()
                    result[path].update(sha256=hashlib.sha256(data).hexdigest(),content_b64=base64.b64encode(data).decode())
        return result

    def cancel_operation(self, identity):
        self.cancelled_operations.add(identity)
        deadline = time.monotonic() + 3
        while True:
            result = self._worker('process.cancel', {'op_id': identity}, 'cancel-' + identity)
            state = self.operations.get(identity)
            if result['cancelled'] or identity not in self.active or (state and state['status']!='started') or time.monotonic()>=deadline:
                return result
            time.sleep(0.02)

    def stream_work_operation(self, args, op_id, *, scope=None):
        if not self.accepting or self.frozen:
            raise DynamicError('environment_not_accepting', 'No work after quiesce or freeze')
        claim = self.operations.claim(op_id, {'operation': 'process.stream', 'args': args})
        if claim['cached']:
            yield from claim['result']['frames']
            return
        if op_id in self.cancelled_operations:
            frames=[{'kind':'exit','result':{'exitCode':None,'timed_out':False,'cancelled_before_start':True}}]
            self.operations.finish(op_id,{'frames':frames})
            yield from frames
            return
        with self.active_lock:
            self.active.add(op_id)
        if self.ledger:
            self.ledger.append('tool_operation_started', {'op_id':op_id, 'operation':'process.stream', 'args':args}, tool_call_id=op_id, **(scope or {}))
        payload = base64.b64encode(canonical({'operation':'process.stream', 'args':args, 'op_id':op_id})).decode()
        process = subprocess.Popen(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
            'exec', self.container, 'python', '-c', self.worker_source, payload], env=self.client_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        frames, finished = [], False
        try:
            for line in process.stdout:
                frame = json.loads(line)
                frames.append(frame)
                if frame['kind'] == 'error':
                    raise DynamicError('remote_' + frame['error_type'], frame['message'])
                if frame['kind'] == 'exit':
                    finished = True
                yield frame
            code = process.wait(timeout=10)
            if code or not finished:
                raise DynamicError('stream_transport_unknown', process.stderr.read()[-1000:])
            stored = self.operations.finish(op_id, {'frames':frames})
            if self.ledger:
                self.ledger.append('tool_operation_finished', {'op_id':op_id, 'exit':frames[-1],
                    'observation_interval':[stored['started_ns'],stored['ended_ns']],
                    'overlapping_operation_ids':stored['overlapping_operation_ids'],
                    'attribution_status':'ambiguous' if stored['overlapping_operation_ids'] else 'single_recorded_operation'}, tool_call_id=op_id, **(scope or {}))
        except BaseException as error:
            if self.operations.get(op_id)['status'] == 'started':
                self.operations.finish(op_id, {'error':type(error).__name__, 'reason':str(error)}, unknown=True)
            raise
        finally:
            process.stdout.close()
            process.stderr.close()
            if process.poll() is None:
                self.cancel_operation(op_id)
                process.wait(timeout=10)
            with self.active_lock:
                self.active.discard(op_id)

    def quiesce(self, deadline: float) -> dict:
        self.accepting = False
        while self.active and time.monotonic() < deadline:
            time.sleep(0.02)
        with self.active_lock:
            active = list(self.active)
        cancelled = []
        for identity in active:
            cancelled.append(self._worker("process.cancel", {"op_id": identity}, "cancel-" + identity))
        return {"status": "quiesced" if not active else "cancel_requested", "active_at_deadline": active, "cancellations": cancelled}

    def freeze(self) -> dict:
        self.accepting = False
        self.freeze_started_ns = time.monotonic_ns()
        self.compose("pause", timeout=30)
        self.frozen = True
        self.freeze_finished_ns = time.monotonic_ns()
        return {"status": "frozen", "cutoff_interval": [self.freeze_started_ns, self.freeze_finished_ns]}

    def stop_epoch_processes(self):
        if self.active:raise DynamicError('old_epoch_active','Drain active work before stopping background workers')
        result=self._worker('process.stop_new',{'baseline':self.baseline_processes},'stop-old-epoch')
        baseline={(row['pid'],row['start_ticks']) for row in self.baseline_processes}
        remaining=[row for row in self._worker('process.snapshot',{},'verify-old-epoch')['processes']
            if (row['pid'],row['start_ticks']) not in baseline]
        if remaining:raise DynamicError('old_epoch_processes_remain','Cannot advance stage with live old workers',evidence=remaining)
        if self.ledger:self.ledger.append('old_epoch_processes_stopped',result)
        return result

    def export_state(self) -> dict:
        if not self.frozen:
            raise DynamicError("export_requires_frozen", "Freeze all branch services first")
        target = self.root / "workspace-frozen.tar"
        data = self.docker("cp", self.container + ":/workspace/.", "-", binary=True).stdout
        target.write_bytes(data)
        result = {"status": "frozen_export", "workspace_tar": str(target), "sha256": hashlib.sha256(data).hexdigest(),
                  "cutoff_interval": [self.freeze_started_ns, self.freeze_finished_ns], "ram_saved": False}
        result['additional_exports']={}
        for name,path in [('mock_api','/opt/mock-api'),('service_log','/tmp/mock-api.log')]:
            copied=self.docker('cp',self.container+':'+path,'-',binary=True,check=False)
            if copied.returncode:
                if b'could not find' in copied.stderr.lower() or b'no such' in copied.stderr.lower():continue
                raise DynamicError('state_export_failed',path)
            file=self.root/(name+'-frozen.tar');file.write_bytes(copied.stdout)
            result['additional_exports'][name]={'path':str(file),'sha256':hashlib.sha256(copied.stdout).hexdigest()}
        result['filesystem_changes']=self.docker('diff',self.container).stdout.splitlines()
        result['home_asset_exports']={}
        home_assets=[row for row in self.case['deployed_assets'] if row['path'].startswith('home/') and row['type'] in ('file','symlink')]
        for row in home_assets:
            path='/root/'+row['path'].removeprefix('home/')
            copied=self.docker('cp',self.container+':'+path,'-',binary=True,check=False)
            if copied.returncode:
                if b'could not find' in copied.stderr.lower() or b'no such' in copied.stderr.lower():
                    result['home_asset_exports'][path]={'status':'absent_at_cutoff'}
                    continue
                raise DynamicError('state_export_failed',path)
            file=self.root/('home-asset-'+hashlib.sha256(path.encode()).hexdigest()[:20]+'.tar')
            file.write_bytes(copied.stdout)
            result['home_asset_exports'][path]={'status':'exported','path':str(file),'sha256':hashlib.sha256(copied.stdout).hexdigest()}
        result['coverage']='workspace, original task home assets, original mock service files/log and complete Docker diff metadata; no RAM or unlisted file contents'
        write_json(self.root / "state-export.json", result)
        return result

    @staticmethod
    def archive_fingerprint(data: bytes) -> list[dict]:
        rows = []
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive:
                row = {"path": member.name, "mode": member.mode, "uid": member.uid, "gid": member.gid,
                       "type": member.type.decode(), "link": member.linkname}
                if member.isfile():
                    row["sha256"] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                rows.append(row)
        return sorted(rows, key=lambda r: r["path"])

    def fingerprint(self) -> dict:
        data = self.docker("cp", self.container + ":/workspace/.", "-", binary=True).stdout
        rows = self.archive_fingerprint(data)
        return {"workspace_hash": digest(rows), "workspace": rows, "image": self.case["deployed_asset_hash"],
                "service_contract": self.case["required_services"], "coverage": "workspace_and_declared_stateless_services"}

    def _top(self) -> list[dict]:
        rows = self.docker("top", self.container, "-eo", "pid,ppid,lstart,args").stdout.splitlines()[1:]
        result = []
        for row in rows:
            fields = row.split(None, 7)
            if len(fields) != 8:
                raise DynamicError("unrecognized_process_table", row)
            result.append({"pid": fields[0], "parent": fields[1], "started": " ".join(fields[2:7]), "command": fields[7]})
        return result

    def _copy_file(self, path: str) -> bytes | None:
        result = self.docker("cp", self.container + ":" + path, "-", binary=True, check=False)
        if result.returncode:
            if b"could not find" in result.stderr.lower() or b"no such" in result.stderr.lower():
                return None
            raise DynamicError("snapshot_file_failed", result.stderr.decode(errors="replace"))
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            members = [m for m in archive if m.isfile()]
            if len(members) != 1:
                raise DynamicError("snapshot_expected_regular_file", path)
            return archive.extractfile(members[0]).read()

    def _service_file_hashes(self) -> dict:
        if not self.case["required_services"]:
            return {}
        return {p: hashlib.sha256(self._copy_file(p)).hexdigest()
                for p in ("/opt/mock-api/app.py", "/opt/mock-api/config.json")}

    def checkpoint_state(self, deadline: float) -> dict:
        """Persist files and explicitly restartable services; never claim RAM capture."""
        self.quiesce(deadline)
        self.freeze()
        baseline = {(r["pid"], r["started"]) for r in self.baseline_top}
        unexpected = [r for r in self._top() if (r["pid"], r["started"]) not in baseline]
        if unexpected:
            raise DynamicError("restore_unsupported", "Unclassified live task processes cannot be restored equivalently", evidence=unexpected)
        if self._service_file_hashes() != self.baseline_service_files:
            raise DynamicError("restore_unsupported", "Service code/config changed; active memory state cannot be inferred from files")
        # Docker commit excludes Docker-managed network files. Export them explicitly.
        files = {}
        for path in ("/etc/hosts", "/etc/hostname", "/etc/resolv.conf", "/tmp/mock-api.log"):
            data = self._copy_file(path)
            if data is not None:
                files[path] = base64.b64encode(data).decode()
        image = "trustfork-snapshot:" + uuid.uuid4().hex
        self.docker("commit", "--no-pause", self.container, image, timeout=120)
        image_id = json.loads(self.docker('image', 'inspect', image).stdout)[0]['Id']
        snapshot = {"schema_version": "1.0", "status": "restartable_filesystem_snapshot", "ram_saved": False,
                    "case": self.case, "compose": self.compose_config, "image_id": image_id,
                    "filesystem_snapshot_id": image_id, "fingerprint": self.fingerprint(),
                    "service_files": self.baseline_service_files, "managed_files": files,
                    "process_contract": "no active work processes; original file-backed mock service may restart",
                    "cutoff_interval": [self.freeze_started_ns, self.freeze_finished_ns]}
        write_json(self.root / "environment-snapshot.json", snapshot)
        return snapshot

    def restore(self, snapshot: dict) -> dict:
        if self.prepared or snapshot.get("ram_saved") is not False or snapshot.get("status") != "restartable_filesystem_snapshot":
            raise DynamicError("invalid_restore_request", "Restore needs a supported frozen filesystem/service snapshot")
        actual = json.loads(self.docker("image", "inspect", snapshot["image_id"]).stdout)[0]["Id"]
        if actual != snapshot["image_id"]:
            raise DynamicError("snapshot_image_mismatch", actual)
        self.case = copy.deepcopy(snapshot["case"])
        self.compose_config = copy.deepcopy(snapshot["compose"])
        for service in self.compose_config["services"].values():
            service["labels"] = {"io.trustfork.dynamic.run": self.run_id}
        self.compose_config["services"]["main"]["image"] = snapshot["image_id"]
        self.config_path.write_text(yaml.safe_dump(self.compose_config, sort_keys=True))
        self.compose("up", "--detach", "--no-build", "--pull", "never", timeout=120)
        self.container = self.compose("ps", "-q", "main").stdout.strip()
        self.prepared = True
        self.start_services()
        for path, data in snapshot["managed_files"].items():
            self._worker("fs.write", {"path": path, "data": data}, "restore-managed")
        self.baseline_processes = self._worker("process.snapshot", {}, "restore-processes")["processes"]
        self.baseline_top = self._top()
        self.baseline_service_files = self._service_file_hashes()
        return self.verify_restored(snapshot)

    def verify_restored(self, expected: dict) -> dict:
        actual = self.fingerprint()
        image_id = json.loads(self.docker("inspect", self.container).stdout)[0]["Image"]
        valid = (actual == expected["fingerprint"] and self._service_file_hashes() == expected["service_files"]
                 and image_id == expected["filesystem_snapshot_id"])
        if not valid:
            raise DynamicError("restore_not_equivalent", "Restored file/service fingerprint differs", evidence={"expected": expected["fingerprint"], "actual": actual})
        return {"status": "verified_restored", "fingerprint": actual, "ram_saved": False,
                "coverage": "immutable committed filesystem, explicitly exported network files, workspace and declared restartable service"}

    def close(self):
        if self.closed:
            return
        if self.config_path.exists():
            ids = self.docker("ps", "-aq", "--filter", "label=" + self.label).stdout.split()
            for identity in ids:
                info = json.loads(self.docker("inspect", identity).stdout)[0]
                if (info["Config"].get("Labels") or {}).get("io.trustfork.dynamic.run") != self.run_id:
                    raise DynamicError("cleanup_owner_mismatch", identity)
                logs = self.docker('logs', identity, check=False)
                (self.root / ('container-' + identity[:12] + '.log')).write_text(logs.stdout + logs.stderr)
                # A paused container cannot gracefully stop. Remove the owned test
                # container directly, without thawing background work after cutoff.
                self.docker('rm', '--force', identity, timeout=30)
            self.compose("down", "--timeout", "3", timeout=45)
        self.operations.close()
        self.closed = True
