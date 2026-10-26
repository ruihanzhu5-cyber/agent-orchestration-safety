"""Shared data primitives, without research semantics or network side effects."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

BASE_COMMIT = "49490514f5187ba4e04b31929f2f4470e0db7def"
BASE_IMAGE = "trustfork-agents:original-49490514-envcheck"
BASE_IMAGE_ID = "sha256:9ca6c9555ff830960857b502eff60b71b669cf3f215dd4543681925bec1186a9"
ORIGINAL_IMAGE = "trustfork-agents:tf-three-harnesses-v1"
WORK_TOOLS = ("read", "bash", "edit", "write", "grep", "find", "ls")
ACTORS = ("Main", "A", "B", "C", "D")


class DynamicError(RuntimeError):
    def __init__(self, code: str, message: str, *, evidence: Any = None):
        super().__init__(code + ': ' + message)
        self.code, self.evidence = code, evidence

    def record(self) -> dict:
        return {"status": "error", "code": self.code, "reason": str(self), "evidence": self.evidence}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def config_dir() -> Path:
    return repo_root() / "trustfork/config/dynamic"


def strict_keys(value: dict, required: set[str], optional: set[str] = frozenset()) -> None:
    if not isinstance(value, dict):
        raise DynamicError("invalid_object", "Expected a JSON object")
    missing, unknown = required - value.keys(), value.keys() - required - optional
    if missing or unknown:
        raise DynamicError("invalid_fields", "Missing or unknown fields", evidence={"missing": sorted(missing), "unknown": sorted(unknown)})


def inventory(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.rglob("*")):
        relative, info = path.relative_to(root).as_posix(), path.lstat()
        if path.is_symlink():
            rows.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            if path.read_bytes().startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise DynamicError("lfs_pointer", f"Unresolved asset: {relative}")
            rows.append({"path": relative, "type": "file", "mode": info.st_mode & 0o7777, "sha256": file_hash(path)})
        elif path.is_dir():
            rows.append({"path": relative, "type": "directory", "mode": info.st_mode & 0o7777})
        else:
            raise DynamicError("unsupported_asset_type", relative)
    return rows
