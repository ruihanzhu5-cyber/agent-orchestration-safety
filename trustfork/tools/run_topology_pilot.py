#!/usr/bin/env python3
"""Prepare/run a small paired pilot through the existing Harbor TaskRunner.

Uses real original tasks and credentials; never generates mock benchmark traces.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from trustfork.tools import generate_jobs as jobs
from trustfork.tools import run_benchmark as runner


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def workspace_hashes(task_dir):
    workspace = task_dir / "environment/workspace"
    return {p.relative_to(workspace).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(workspace.rglob("*")) if p.is_file()}


def summarize(config, status):
    directory = Path(config["jobs_dir"]) / config["job_name"]
    annotations = list(directory.rglob("annotations.json"))
    annotation = runner.read_json(annotations[-1]) if annotations else {}
    trials = [p for p in directory.rglob("result.json") if p.parent != directory]
    trial = runner.read_json(trials[-1]) if trials else {}
    metrics = (trial or {}).get("agent_result") or {}
    native_usage = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "reported_cost_usd": 0.0}
    seen = set()
    def collect(value):
        identity = value.get("trajectory_id") or value.get("session_id")
        if identity in seen:
            return
        seen.add(identity)
        final = value.get("final_metrics") or {}
        for target, field in (("prompt_tokens", "total_prompt_tokens"), ("completion_tokens", "total_completion_tokens"),
                              ("cached_tokens", "total_cached_tokens"), ("reported_cost_usd", "total_cost_usd")):
            native_usage[target] += final.get(field) or 0
        for child in value.get("subagent_trajectories", []) or []:
            collect(child)
    for path in directory.rglob("trajectory.json"):
        value = runner.read_json(path)
        if isinstance(value, dict):
            collect(value)
    ledgers = list(directory.rglob("topology/events.jsonl"))
    events = []
    for ledger in ledgers:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    judge_requests = Counter()
    judge_repairs = []
    if annotations:
        for request in annotations[-1].parent.glob("judge_*_request_*.json"):
            info = runner.read_json(request) or {}
            judge_requests[info.get("pass", "unknown")] += 1
        for attempt in annotations[-1].parent.glob("judge_*_attempt_*.json"):
            info = runner.read_json(attempt) or {}
            judge_repairs.append({key: info.get(key) for key in ("pass", "attempt", "error_type", "error", "finish_reason")})
    return {
        "status": status.get("status"), "retained_attempt": status.get("retained_attempt"),
        "result_directory": str(directory), "trajectory_paths": [str(p) for p in directory.rglob("trajectory.json")],
        "scorer_output": str(annotations[-1]) if annotations else None,
        "report_scores": (annotation or {}).get("benchmark_scores", {}).get("report_score_0_100"),
        "breadth_validation": (annotation or {}).get("breadth_validation"),
        "topology_process": (annotation or {}).get("topology_process"),
        "input_tokens": metrics.get("n_input_tokens"), "output_tokens": metrics.get("n_output_tokens"),
        "trial_started_at": (trial or {}).get("started_at"),
        "trial_finished_at": (trial or {}).get("finished_at"),
        "agent_execution": (trial or {}).get("agent_execution"),
        "verifier_execution": (trial or {}).get("verifier"),
        "cost_usd_reported_by_harness": metrics.get("cost_usd"),
        "all_native_sessions_usage": native_usage,
        "judge_requests_by_pass": dict(judge_requests),
        "judge_schema_repairs": judge_repairs,
        "cost_caveat": "Gateway/custom-model prices may not be registered; missing/zero cost is not proof of free use. Judge billing is separate.",
        "runtime_event_files": [str(p) for p in ledgers],
        "runtime_group_errors": [event for event in events if event.get("event") == "group_failed"],
        "error_paths": [str(p) for p in directory.rglob("exception.txt")],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", required=True, help="backbone@opencode")
    parser.add_argument("--tasks", nargs="+", default=["trustfork_0018"])
    parser.add_argument("--topologies", nargs="+", choices=["original", "chain", "debate"], default=["original", "chain", "debate"])
    parser.add_argument("--systems-config", type=Path, default=jobs.SYSTEMS_CONFIG)
    parser.add_argument("--pools-config", type=Path, default=jobs.POOLS_CONFIG)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--proxy-compose", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout-multiplier", type=float, default=1.0)
    parser.add_argument("--execute", action="store_true", help="Real API calls and disposable Harbor containers")
    args = parser.parse_args()
    backbone, harness = args.system.split("@", 1)
    if harness != "opencode":
        raise SystemExit("Pilot runtime v1 supports OpenCode only")
    out = (args.out or ROOT / "build/topology-pilot" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    systems = yaml.safe_load(args.systems_config.read_text(encoding="utf-8"))
    backbones = systems["backbones"]
    model = backbones[backbone]
    pools = jobs.load_json(args.pools_config)["templates"]
    goals = jobs.load_json(jobs.GOALS_CONFIG)
    configs, manifest = [], {"status": "prepared", "system": args.system, "seed": None,
        "determinism": "Native harness/API seed not guaranteed; no claimed deterministic sampling",
        "budget": {"timeout_multiplier": args.timeout_multiplier, "aggregate_token_limit": None}, "runs": []}
    for task_id in args.tasks:
        matches = [p for p in jobs.TASKS_ROOT.glob(f"*/{task_id}") if (p / "task.toml").exists()]
        if len(matches) != 1:
            raise SystemExit(f"Expected exactly one original task: {task_id}")
        source = matches[0]
        task = jobs.load_json(source / "tests/task_spec.private.json")
        if task["breadth_regime"] != "b4":
            raise SystemExit(f"{task_id}: paired pilot requires original b4")
        if task["pool_template_id"] not in pools:
            raise SystemExit(f"{task_id}: pool {task['pool_template_id']} is absent from --pools-config; task settings will not be changed")
        pool = jobs.resolve_pool(pools[task["pool_template_id"]], model, backbones, systems["model_registry"], task)
        display = jobs.render_display(task, pool, model)
        metadata = jobs.load_json(source / "tests/task_metadata.json")
        goal = goals[task["actor_goal_id"]].get("focal_prompt")
        prompts = {slot: None for slot in pool}
        if goal:
            prompts[task["focal_actor_slot"]] = goal.format(attack_goal=metadata.get("attack_goal", ""))
        for topology in args.topologies:
            system_id = f"{backbone}__{harness}" + (f"__topo-{topology}" if topology != "original" else "")
            config = jobs.job_config(system_id, harness, model, systems["providers"], source, task, pool, display, prompts, topology=topology)
            if topology == "original":
                copied = out / "original-tasks" / task_id
                shutil.copytree(source, copied, dirs_exist_ok=True)
                for script in copied.rglob("*.sh"):
                    script.write_bytes(script.read_bytes().replace(b"\r\n", b"\n"))
                config["datasets"][0]["path"] = str(copied.parent)
            else:
                config["datasets"][0]["path"] = str(ROOT / config["datasets"][0]["path"])
            config["jobs_dir"] = str(out / "jobs")
            config["timeout_multiplier"] = args.timeout_multiplier
            if args.proxy_compose:
                config["environment"]["extra_docker_compose"] = [str(args.proxy_compose.resolve())]
            # Same transport-only model limit in every arm, required by this gateway.
            provider = config["agents"][0]["kwargs"]["opencode_config"]["provider"]
            for entry in provider.values():
                if "gpt-4o" in entry.get("models", {}):
                    entry["models"]["gpt-4o"]["limit"] = {"context": 128000, "output": 16384}
            path = out / "configs" / f"{config['job_name']}.json"
            json_write(path, config)
            configs.append((path, config))
            manifest["runs"].append({"task_id": task_id, "topology": topology, "model": backbone,
                "harness": harness, "identity_setting": task["identity_display_id"],
                "attack_goal": metadata.get("attack_goal"), "breadth": task["breadth_regime"],
                "actual_models": {slot: data["api_model"] for slot, data in pool.items()},
                "displayed_identities": display, "private_goal_hashes": {slot: hashlib.sha256((text or "").encode()).hexdigest() for slot, text in prompts.items()},
                "task_assets": workspace_hashes(source),
                "declared_task_assets": metadata.get("initial_workspace_sha256"),
                "config": str(path), "result": None})
    json_write(out / "pilot.json", manifest)
    print(f"Prepared {len(configs)} configurations: {out}", flush=True)
    if not args.execute:
        return
    if sys.platform != "linux":
        raise SystemExit("Use Linux/WSL Harbor for allowlisted Docker execution")
    harbor_bin = os.environ.get("HARBOR_BIN") or str(Path(sys.executable).with_name("harbor"))
    if not Path(harbor_bin).is_file():
        raise SystemExit("Harbor executable not found beside the active Python; set HARBOR_BIN")
    runner.HARBOR_BIN = harbor_bin
    runner.load_env_file(args.env_file)
    if not all(os.environ.get(key) for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY")):
        raise SystemExit("Existing API configuration is incomplete; no key values are printed")
    subprocess.run([sys.executable, str(runner.ENSURE_BASE_IMAGE)], cwd=ROOT, check=True)
    ledger_path = out / "ledger.json"
    task_runner = runner.TaskRunner(runner.load_ledger(ledger_path), ledger_path)
    for (path, config), row in zip(configs, manifest["runs"]):
        print(f"Running {row['task_id']} / {row['topology']}", flush=True)
        _, entry = task_runner.run(path, config["job_name"], False)
        row["result"] = summarize(config, entry)
        json_write(out / "pilot.json", manifest)
        print(f"Completed {row['topology']}: {entry['status']}", flush=True)
    manifest["status"] = "finished"
    json_write(out / "pilot.json", manifest)
    print(f"Pilot record: {out / 'pilot.json'}", flush=True)


if __name__ == "__main__":
    main()
