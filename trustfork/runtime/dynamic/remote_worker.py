"""Public operation worker sent to the task container, never a host shell.

This module contains no goals, credentials, score data or control-side paths.
It uses only the Python standard library available in the audited image.
"""
from __future__ import annotations

import base64
import json
import os
import re
import signal
import stat
import subprocess
import sys
from pathlib import Path


def b64(data):
    return base64.b64encode(data).decode("ascii")


def process_table():
    result = []
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit() or int(directory.name) == os.getpid():
            continue
        try:
            fields = (directory / "stat").read_text().split(") ", 1)[1].split()
            command = (directory / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
            if fields[0] == "Z":
                continue
            result.append({"pid": int(directory.name), "ppid": int(fields[1]),
                           "start_ticks": int(fields[19]), "command": command})
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result


def execute(request):
    operation, args = request["operation"], request["args"]
    if operation == "fs.read":
        return {"data": b64(Path(args["path"]).read_bytes())}
    if operation == "fs.write":
        data = base64.b64decode(args["data"], validate=True)
        Path(args["path"]).write_bytes(data)
        return {"written": len(data)}
    if operation == "fs.access":
        path = Path(args["path"])
        if not path.exists():
            raise FileNotFoundError(str(path))
        if not os.access(path, args.get("mode", os.R_OK)):
            raise PermissionError(str(path))
        return {"accessible": True}
    if operation == "fs.mkdir":
        Path(args["path"]).mkdir(parents=True, exist_ok=True)
        return {"created": True}
    if operation == "fs.exists":
        return {"exists": Path(args["path"]).exists()}
    if operation == "fs.stat":
        info = Path(args["path"]).stat()
        return {"isDirectory": stat.S_ISDIR(info.st_mode), "mode": info.st_mode & 0o7777,
                "size": info.st_size, "uid": info.st_uid, "gid": info.st_gid}
    if operation == "fs.readdir":
        return {"entries": os.listdir(args["path"])}
    if operation == "fs.glob":
        command = ["rg", "--files", "--hidden", "--glob", args["pattern"]]
        for ignore in args.get("ignore", []):
            command += ["--glob", "!" + ignore]
        command += ["."]
        process = subprocess.run(command, cwd=args["cwd"], capture_output=True, text=True)
        if process.returncode not in (0, 1):
            raise RuntimeError(process.stderr.strip())
        return {"paths": [Path(p).as_posix() for p in process.stdout.splitlines()[:args["limit"]]]}
    if operation == "process.snapshot":
        return {"processes": process_table()}
    if operation == "process.cancel":
        identity = args["op_id"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", identity):
            raise ValueError("Invalid operation ID")
        pidfile = Path("/tmp/trustfork-operations") / (identity + ".pid")
        if not pidfile.exists():
            return {"cancelled": False, "reason": "no_active_process"}
        pid = int(pidfile.read_text())
        try:
            os.killpg(pid, signal.SIGKILL)
            return {"cancelled": True}
        except ProcessLookupError:
            return {"cancelled": False, "reason": "already_exited"}
    if operation in {"process.bash", "process.argv"}:
        identity = request["op_id"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", identity):
            raise ValueError("Invalid operation ID")
        command = ["/bin/bash", "-c", args["command"]] if operation == "process.bash" else args["argv"]
        directory = Path("/tmp/trustfork-operations")
        directory.mkdir(mode=0o700, exist_ok=True)
        pidfile = directory / (identity + ".pid")
        process = subprocess.Popen(command, cwd=args.get("cwd", "/workspace"),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        pidfile.write_text(str(process.pid))
        try:
            try:
                output, _ = process.communicate(timeout=args.get("timeout"))
                return {"output": b64(output), "exitCode": process.returncode, "timed_out": False}
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, _ = process.communicate()
                return {"output": b64(output), "exitCode": None, "timed_out": True}
        finally:
            pidfile.unlink(missing_ok=True)
    raise ValueError("Unknown operation: " + str(operation))


if __name__ == "__main__":
    request = json.loads(base64.b64decode(sys.argv[1], validate=True))
    try:
        result = {"ok": True, "result": execute(request)}
    except (OSError, ValueError, RuntimeError) as error:
        result = {"ok": False, "error_type": type(error).__name__, "message": str(error)}
    print(json.dumps(result, ensure_ascii=False), flush=True)
