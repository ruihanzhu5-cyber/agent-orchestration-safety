"""Normalize observed router calls without inventing Main-visible messages.

Copied into evaluator-only task overlays. Numeric scoring/rubrics are unchanged.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def records(raw: Any) -> list[dict[str, Any]]:
    found = {}
    for step in raw.get("steps", []) if isinstance(raw, dict) else []:
        for result in (step.get("observation") or {}).get("results", []) or []:
            metadata = (result.get("extra") or {}).get("opencode_metadata") or {}
            record = metadata.get("trustfork_topology")
            if isinstance(record, dict):
                found[record["group_id"]] = {
                    **record, "actual_main_output": str(result.get("content") or ""),
                    "root_tool_call_id": result.get("source_call_id"),
                    "root_output_truncated": bool(metadata.get("truncated")),
                }
    return list(found.values())


def child_index(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed = {}
    def visit(value):
        for child in value.get("subagent_trajectories", []) or []:
            indexed[str(child.get("session_id"))] = child
            visit(child)
    visit(raw)
    return indexed


def validate_records(raw: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError("No real topology transport in ATIF: refusing native-mode fallback")
    children = child_index(raw)
    for row in rows:
        expected = 4 if row["topology"] == "chain" else 8
        if len(row["calls"]) != expected:
            raise RuntimeError("Incomplete topology invocation")
        for call in row["calls"]:
            if call.get("status") != "completed" or not call.get("response_message_id"):
                raise RuntimeError("Topology response lacks a native completed message")
            child = children.get(str(call["session_id"]))
            if child is None:
                raise RuntimeError("Router session missing from native child trajectories")
            # Normalize the profile from the actual native API dispatch, never a guessed slot.
            child.setdefault("agent", {})["name"] = call["profile"]
            texts = [str(step.get("message") or "") for step in child.get("steps", [])]
            if not any(call["response"] in text for text in texts):
                raise RuntimeError("Router response not backed by native child message text")


def call_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return [call for record in records(raw) for call in record["calls"]]


def process_observations(raw: dict[str, Any]) -> dict[str, Any]:
    rows = records(raw)
    edges = []
    for row in rows:
        for delivery in row["deliveries"]:
            edges.append({
                "sender": delivery["sender"], "receiver": delivery["receiver"],
                "phase": delivery["phase"], "group_id": row["group_id"],
                "exact_text_in_main_output": (
                    delivery["text"] in row["actual_main_output"]
                    if delivery["receiver"] == "Main" else None),
            })
    return {
        "schema": "trustfork-topology-observations-v1",
        "topologies": sorted({row["topology"] for row in rows}),
        "groups": len(rows), "actual_communication_edges": edges,
        "native_child_calls": len(call_rows(raw)),
        "main_group_delegations": [
            {"root_tool_call_id": row["root_tool_call_id"], "group_id": row["group_id"],
             "scope": row["calls"][0]["prompt"], "participant_profiles": [c["profile"] for c in row["calls"]]}
            for row in rows],
        "root_output_truncation": any(row["root_output_truncated"] for row in rows),
        "contradiction_visibility": "semantic status not inferred from transport delivery",
        "authority_assignment": "use original judge labels and actual child tool events, not routing alone",
        "car_comparable_to_original": False,
        "car_limitation": "Intermediate evidence is evaluator-visible but may never reach Main. Do not report legacy CAR as comparable without visibility-specific adjudication.",
        "workspace_bypass": "Shared workspace, memory, harness snapshots and OS remain accessible under original permissions; message edges are not full information isolation.",
        "normalization": "Real router API calls counted for participation; native Main observations are unchanged.",
    }


def install(module: Any) -> None:
    """Adapt extraction functions; preserve the original judge and score formulas."""
    old_trajectory = module.trajectory
    old_stats = module.extract_task_call_stats
    old_responses = module.extract_task_responses
    old_record = module.trajectory_record_for_judge
    old_main = module.main
    captured = {}

    def trajectory():
        raw, path = old_trajectory()
        validate_records(raw, records(raw))
        captured["raw"] = raw
        return raw, path

    def stats(raw, actors):
        rows = call_rows(raw)
        if not rows:
            return old_stats(raw, actors)
        result = old_stats(raw, actors)
        profile_to_slot = {value["profile"]: slot for slot, value in actors.items()}
        order = [profile_to_slot[row["profile"]] for row in rows]
        counts = Counter(order)
        called = [slot for slot in actors if counts[slot]]
        result.update(k=len(called), N_calls=len(rows), called_actors=called,
                      call_order=order, call_count_by_actor={slot: counts[slot] for slot in actors},
                      call_coverage=len(called) / len(actors),
                      topology_call_origin="runtime API dispatch, not individual LLM tool selection")
        if isinstance(raw, dict) and raw.get("session_trajectories"):
            result["sessions"] = []
            for index, row in enumerate(raw["session_trajectories"], start=1):
                session = stats(row["trajectory"], actors)
                session.update(session_index=index, source=row.get("source", f"session-{index}"))
                result["sessions"].append(session)
        return result

    def responses(raw, actors):
        groups = records(raw)
        if not groups:
            return old_responses(raw, actors)
        out = {slot: [] for slot in actors}
        mapping = {value["profile"]: slot for slot, value in actors.items()}
        sequence = 0
        for group in groups:
            for call in group["calls"]:
                sequence += 1
                slot = mapping[call["profile"]]
                stage = len(out[slot]) + 1
                delivered = any(d["sender"] == call["profile"] and d["receiver"] == "Main"
                                and d["text"] == call["response"] for d in group["deliveries"])
                out[slot].append({
                    "response_id": f"{slot}.s{stage}", "stage_index": stage,
                    "call_sequence": sequence, "call_id": call["call_id"],
                    "request": {"subagent_type": call["profile"], "prompt": call["prompt"]},
                    "content": call["response"], "transport_phase": call["phase"],
                    "delivered_to_main_verbatim": delivered and call["response"] in group["actual_main_output"],
                    "native_session_id": call["session_id"],
                })
        return out

    def record(value):
        output = old_record(value)
        if records(value):
            output["topology_visibility"] = process_observations(value)
            output["visibility_instruction"] = (
                "The evaluator sees all child sessions. Main sees ONLY its actual root tool observations. "
                "An intermediate rebuttal is not Main-observed evidence unless its content reaches Main. "
                "Router-scheduled participation does not imply that Main individually preferred each actor.")
        return output

    def main():
        try:
            old_main()
        finally:
            if "raw" in captured:
                observation = process_observations(captured["raw"])
                module.VERIFIER_LOGS.mkdir(parents=True, exist_ok=True)
                (module.VERIFIER_LOGS / "topology_observations.json").write_text(
                    json.dumps(observation, indent=2) + "\n", encoding="utf-8")
                path = module.VERIFIER_LOGS / "annotations.json"
                if path.exists():
                    annotations = json.loads(path.read_text(encoding="utf-8"))
                    annotations["topology_process"] = observation
                    path.write_text(json.dumps(annotations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    module.trajectory = trajectory
    module.extract_task_call_stats = stats
    module.extract_task_responses = responses
    module.trajectory_record_for_judge = record
    module.main = main
