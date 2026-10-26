"""Append-only evidence; event identity is distinct from identical content."""
from __future__ import annotations

import hashlib
import copy
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .common import DynamicError, canonical, digest
from .schema import validate_contract


class EvidenceStore:
    def __init__(self, root: Path, branch_id: str):
        self.root, self.branch_id = root, branch_id
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, value: Any) -> str:
        data = canonical(value)
        identity = hashlib.sha256(data).hexdigest()
        target = self.root / (identity + ".json")
        if target.exists():
            if target.read_bytes() != data:
                raise DynamicError("hash_collision", identity)
        else:
            with target.open("xb") as stream:
                stream.write(data)
        return "evidence://" + identity

    def get(self, reference: str, *, branch_id: str) -> Any:
        if branch_id != self.branch_id:
            raise DynamicError("cross_branch_reference", "Evidence is branch scoped")
        if not reference.startswith("evidence://"):
            raise DynamicError("invalid_reference", reference)
        identity = reference.removeprefix("evidence://")
        if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise DynamicError("invalid_reference", reference)
        data = (self.root / (identity + ".json")).read_bytes()
        if hashlib.sha256(data).hexdigest() != identity:
            raise DynamicError("evidence_hash_mismatch", identity)
        return json.loads(data)


class EventLedger:
    def __init__(self, path: Path, branch_id: str, task_id: str):
        self.path, self.branch_id, self.task_id = path, branch_id, task_id
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.listeners=[]
        self.rows = []
        if path.exists():
            self.rows = [json.loads(line) for line in path.read_text().splitlines()]
            for number, row in enumerate(self.rows, 1):
                validate_contract('EventEnvelope',row)
                if row["sequence"] != number or row["payload_hash"] != digest(row["payload"]):
                    raise DynamicError("invalid_event_ledger", f"Invalid event {number}")
                if row["branch_id"] != branch_id or row["task_id"] != task_id:
                    raise DynamicError("cross_branch_event", "Ledger owner differs")

    def append(self, event_type: str, payload: dict, *, actor_id: str | None = None,
               stage_id: str = "initial", stage_epoch: int = 0, **references: Any) -> dict:
        allowed = {"request_id", "tool_call_id", "message_id", "invocation_id"}
        if references.keys() - allowed:
            raise DynamicError("invalid_event_reference", str(references.keys() - allowed))
        with self.lock:
            payload = json.loads(canonical(payload))
            sequence = len(self.rows) + 1
            row = {"schema_version": "1.0", "event_id": f"event_{sequence:08d}",
                   "sequence": sequence, "monotonic_ns": time.monotonic_ns(),
                   "branch_id": self.branch_id, "task_id": self.task_id,
                   "stage_id": stage_id, "stage_epoch": stage_epoch,
                   "actor_id": actor_id, "event_type": event_type,
                   **{k: references.get(k) for k in sorted(allowed)},
                   "payload": payload, "payload_hash": digest(payload)}
            validate_contract('EventEnvelope',row)
            with self.path.open("ab") as stream:
                stream.write(canonical(row) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.rows.append(row)
            for listener in self.listeners:listener(row)
            return copy.deepcopy(row)

    def require_event(self, identity: str) -> dict:
        for row in self.rows:
            if row["event_id"] == identity:
                return row
        raise DynamicError("missing_evidence_event", identity)
