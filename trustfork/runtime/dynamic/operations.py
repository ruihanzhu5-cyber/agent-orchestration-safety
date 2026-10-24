"""Durable operation claims. A started operation is never blindly replayed."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .common import DynamicError, canonical, digest


class OperationStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, input_hash TEXT NOT NULL, status TEXT NOT NULL, started_ns INTEGER, ended_ns INTEGER, overlaps TEXT NOT NULL, result TEXT)")
        self.lock = threading.RLock()

    def get(self, identity: str) -> dict | None:
        with self.lock:
            row = self.connection.execute("SELECT * FROM operations WHERE id=?", (identity,)).fetchone()
        if row is None:
            return None
        return dict(zip(("op_id", "input_hash", "status", "started_ns", "ended_ns", "overlapping_operation_ids", "result"),
                        (row[0], row[1], row[2], row[3], row[4], json.loads(row[5]), json.loads(row[6]) if row[6] else None)))

    def claim(self, identity: str, request: dict) -> dict:
        fingerprint = digest(request)
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self.connection.execute("SELECT input_hash,status,result FROM operations WHERE id=?", (identity,)).fetchone()
                if existing:
                    if existing[0] != fingerprint:
                        raise DynamicError("operation_id_reused", identity)
                    if existing[1] != "completed":
                        raise DynamicError("operation_effect_unknown", "Already started operation cannot be re-executed", evidence=identity)
                    result = json.loads(existing[2])
                    self.connection.execute("COMMIT")
                    return {"cached": True, "result": result}
                self.connection.execute("INSERT INTO operations VALUES (?,?,?,NULL,NULL,?,NULL)", (identity, fingerprint, "prepared", "[]"))
                active = [r[0] for r in self.connection.execute("SELECT id FROM operations WHERE status='started'")]
                for other in active:
                    overlaps = json.loads(self.connection.execute("SELECT overlaps FROM operations WHERE id=?", (other,)).fetchone()[0])
                    self.connection.execute("UPDATE operations SET overlaps=? WHERE id=?", (json.dumps([*overlaps, identity]), other))
                self.connection.execute("UPDATE operations SET status='started',started_ns=?,overlaps=? WHERE id=?", (time.monotonic_ns(), json.dumps(active), identity))
                self.connection.execute("COMMIT")
                return {"cached": False}
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise

    def finish(self, identity: str, result: dict, *, unknown: bool = False) -> dict:
        with self.lock:
            cursor = self.connection.execute("UPDATE operations SET status=?,ended_ns=?,result=? WHERE id=? AND status='started'", ("effect_unknown" if unknown else "completed", time.monotonic_ns(), canonical(result).decode(), identity))
            if cursor.rowcount != 1:
                raise DynamicError("invalid_operation_transition", identity)
        return self.get(identity)

    def close(self) -> None:
        self.connection.close()
