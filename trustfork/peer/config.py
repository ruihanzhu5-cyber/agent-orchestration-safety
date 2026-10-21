"""Install a standalone Peer runtime and evaluator-only task overlay."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

from .protocol import PeerSpec

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
WRAPPER = '''#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from peer_verifier import run
spec = importlib.util.spec_from_file_location("native_verifier", Path(__file__).with_name("native_verifier.py"))
native = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = native
spec.loader.exec_module(native)
run(native)
'''


def prepare_peer_task(task_dir: Path, spec: PeerSpec, root: Path = ROOT) -> Path:
    scorer = root / "trustfork/scoring/peer_verifier.py"
    additions = {"peer_protocol.py": (HERE / "protocol.py").read_bytes(),
                 "peer_verifier.py": scorer.read_bytes()}
    digest = hashlib.sha256(WRAPPER.encode())
    for name, data in sorted(additions.items()):
        digest.update(name.encode() + b"\0" + data)
    for path in sorted(p for p in task_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(task_dir).as_posix().encode() + b"\0" + path.read_bytes())
    destination = root / "build/peer-tasks" / spec.mode / digest.hexdigest()[:20] / task_dir.name
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=destination.parent))
    try:
        shutil.copytree(task_dir, temporary, dirs_exist_ok=True)
        for original in task_dir.rglob("tests/verifier.py"):
            target = temporary / original.relative_to(task_dir)
            shutil.copyfile(original, target.with_name("native_verifier.py"))
            target.write_text(WRAPPER, encoding="utf-8", newline="\n")
            for name, content in additions.items():
                target.with_name(name).write_bytes(content)
        for script in temporary.rglob("*.sh"):
            script.write_bytes(script.read_bytes().replace(b"\r\n", b"\n"))
        # Harbor changes /logs between stages. Preserve stage-one audit alongside
        # the native evaluator's existing trajectory snapshot, never as tool output.
        first_test = temporary / "steps/inject_poison/tests/test.sh"
        first_test.write_text(first_test.read_text(encoding="utf-8") + '''
mkdir -p /workspace/.trustfork-harness/peer
if [ -f /logs/agent/opencode/peer/peer_events.jsonl ]; then
  cp /logs/agent/opencode/peer/peer_events.jsonl /workspace/.trustfork-harness/peer/01_events.jsonl
fi
''', encoding="utf-8", newline="\n")
        # Windows scanners can briefly hold newly copied .py files open.
        # Keep publication atomic; never expose a half-copied cache directory.
        for attempt in range(6):
            try:
                temporary.rename(destination)
                break
            except PermissionError:
                if destination.exists():
                    break  # identical content-addressed cache published concurrently
                if attempt==5:
                    raise
                time.sleep(0.1*(attempt+1))
    finally:
        if temporary.exists():
            if not temporary.resolve().is_relative_to((root / "build/peer-tasks").resolve()):
                raise RuntimeError("Cleanup path escaped Peer cache")
            shutil.rmtree(temporary)
    return destination


def apply_peer(config: dict, spec: PeerSpec, harness: str, task_dir: Path, task: dict, root: Path = ROOT) -> dict:
    spec.validate(harness, task)
    if spec.mode == "original":
        return config
    agent = config["agents"][0]
    if agent["kwargs"].get("opencode_plugins"):
        raise ValueError("Peer and defense/runtime plugins cannot be combined")
    manifest = {"peer_protocol": "trustfork-peer-v0.3", "peer_mode": spec.mode,
                "task_id": task["task_id"], "source_profile": task["actors"][task["focal_actor_slot"]]["profile"],
                "recipient_profile": task["actors"][spec.recipient]["profile"]}
    agent["kwargs"]["opencode_plugins"] = {"trustfork-peer.js": (HERE / "runtime.js").read_text(encoding="utf-8").replace(
        "__TRUSTFORK_PEER_SPEC__", json.dumps(manifest))}
    # Harbor 0.24 prioritizes a builtin name over import_path. Peer must load
    # the vendored adapter; native Original generation remains untouched.
    agent.pop("name", None)
    overlay = prepare_peer_task(task_dir, spec, root)
    config["datasets"][0]["path"] = overlay.parent.relative_to(root).as_posix()
    config["verifier"]["env"]["TRUSTFORK_PEER_MODE"] = spec.mode
    config["verifier"]["env"]["TRUSTFORK_PEER_RECIPIENT"] = spec.recipient
    config["verifier"]["include_logs"] += ["peer_*.json"]
    config["artifacts"] = [*(config.get("artifacts") or []), {
        "source": "/workspace", "destination": "workspace", "exclude": [".trustfork-harness", ".git"]}]
    return config
