from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class TopologySpec:
    name: str
    order: str = "ABCD"

    def __post_init__(self) -> None:
        if self.name not in {"original", "chain", "debate"}:
            raise ValueError(f"Unknown topology: {self.name}")
        if len(self.order) != 4 or set(self.order) != set("ABCD"):
            raise ValueError("Topology order must be a permutation of ABCD")

    def validate_task(self, harness: str, task: dict[str, Any]) -> None:
        if self.name == "original":
            return
        if harness != "opencode":
            raise ValueError(f"Topology {self.name} is not supported on {harness}")
        if task.get("breadth_regime") != "b4" or task.get("target_breadth") != 4:
            raise ValueError("Chain/Debate require an original b4 task; no fallback")


WRAPPER = '''#!/usr/bin/env python3
"""Normalize real router transport; retain the original task verifier."""
import importlib.util
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from topology_scoring import install
spec = importlib.util.spec_from_file_location("trustfork_original", Path(__file__).with_name("verifier_original.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
install(module)
module.main()
'''


def prepare_task(task_dir: Path, spec: TopologySpec, root: Path = ROOT) -> Path:
    # Pin each overlay to its contents so later preparations cannot rewrite an
    # evaluator directory already referenced by a running Harbor job.
    digest = hashlib.sha256(WRAPPER.encode() + (HERE / "scoring.py").read_bytes())
    for path in sorted(p for p in task_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(task_dir).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    destination = root / "build" / "tasks_topology" / spec.name / digest.hexdigest()[:20] / task_dir.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_dir():
        return destination
    temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=destination.parent))
    try:
        shutil.copytree(task_dir, temporary, dirs_exist_ok=True)
        for source in task_dir.rglob("verifier.py"):
            if source.parent.name != "tests":
                continue
            target = temporary / source.relative_to(task_dir)
            shutil.copyfile(source, target.with_name("verifier_original.py"))
            shutil.copyfile(HERE / "scoring.py", target.with_name("topology_scoring.py"))
            target.write_text(WRAPPER, encoding="utf-8", newline="\n")
        for script in temporary.rglob("*.sh"):
            script.write_bytes(script.read_bytes().replace(b"\r\n", b"\n"))
        try:
            temporary.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
    finally:
        if temporary.exists():
            cache_root = (root / "build" / "tasks_topology").resolve()
            if not temporary.resolve().is_relative_to(cache_root):
                raise RuntimeError("Refusing cleanup outside topology cache")
            shutil.rmtree(temporary)
    return destination


def apply_topology(config: dict[str, Any], spec: TopologySpec, harness: str,
                   task_dir: Path, task: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    spec.validate_task(harness, task)
    if spec.name == "original":
        return config
    kwargs = config["agents"][0]["kwargs"]
    if kwargs.get("opencode_plugins"):
        raise ValueError("Topology and defense plugins cannot be combined in v1")
    manifest = {"schema": "trustfork-topology-v1", "topology": spec.name,
                "order": list(spec.order), "task_id": task["task_id"]}
    source = (HERE / "runtime.js").read_text(encoding="utf-8")
    kwargs["opencode_plugins"] = {"trustfork-topology.js": source.replace(
        "__TRUSTFORK_TOPOLOGY_SPEC__", json.dumps(manifest))}
    copied = prepare_task(task_dir, spec, root)
    config["datasets"][0]["path"] = copied.parent.relative_to(root).as_posix()
    config["verifier"]["include_logs"].append("topology_observations.json")
    return config
