"""Peer roles, message provenance and factual path validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any

MODES = ("original", "direct", "peer_control", "peer_chain")


@dataclass(frozen=True)
class PeerSpec:
    mode: str
    recipient: str = "B"

    def validate(self, harness: str, task: dict[str, Any]) -> None:
        if self.mode not in MODES:
            raise ValueError("Unknown peer_mode")
        if self.mode == "original":
            return
        if harness != "opencode":
            raise ValueError("Peer v0.1 supports OpenCode only")
        if task.get("task_id") != "trustfork_0451" or task.get("breadth_regime") != "free":
            raise ValueError("Peer pilot is restricted to unmodified trustfork_0451/free")
        if self.recipient not in "ABCD" or len(self.recipient) != 1:
            raise ValueError("Recipient must be a roster slot")
        if self.recipient == task["focal_actor_slot"]:
            raise ValueError("Peer recipient must be a different, user-aligned member")
        if task["actors"][self.recipient]["actor_goal_id"] != "user_aligned":
            raise ValueError("Peer recipient has a private risky goal")


@dataclass(frozen=True)
class PeerMessage:
    message_id: str
    sender: str
    receiver: str
    parent_message_ids: list[str]
    content: str
    content_sha256: str
    stage: str

    @classmethod
    def create(cls, message_id, sender, receiver, content, stage, parents=()):
        return cls(message_id, sender, receiver, list(parents), content,
                   hashlib.sha256(content.encode("utf-8")).hexdigest(), stage)


def route_message(events: list[dict], message: PeerMessage, **fields) -> dict:
    row = {"event": "message", **asdict(message), **fields}
    events.append(row)
    return row


def get_visible_messages(events: list[dict], actor_id: str) -> list[dict]:
    return [e for e in events if e.get("event") == "message" and e.get("receiver") == actor_id]


def validate_peer_path(events: list[dict], raw: dict) -> dict:
    """Check actual native inputs/outputs, not synthetic router descriptions."""
    definitions = [e for e in events if e.get("event") == "task_definition"]
    identity_required = any(e.get("peer_protocol") == "trustfork-peer-v0.3" for e in events)
    if identity_required:
        if not definitions:
            raise ValueError("Missing native task definition / displayed identity evidence")
        for definition in definitions:
            roster = definition.get("displayed_roster", {})
            description = definition.get("description", "")
            if (set(roster) != {f"candidate_{slot}" for slot in "abcd"}
                or any(not isinstance(label, str) or not label.strip()
                       or f"{profile}: {label}" not in description for profile, label in roster.items())
                or hashlib.sha256(description.encode()).hexdigest() != definition.get("description_sha256")):
                raise ValueError("Invalid public identity roster / native task definition hash")
    children = {}
    def visit(value):
        for child in value.get("subagent_trajectories", []) or []:
            children[child["session_id"]] = child
            visit(child)
    visit(raw)
    completed = [e for e in events if e.get("event") == "call_completed"]
    if not completed:
        raise ValueError("No real Peer/native calls recorded")
    for call in completed:
        child = children.get(call["session_id"])
        if child is None:
            raise ValueError("Peer session absent from native trajectory")
        matching = [s for s in child["steps"] if s.get("source") == "agent"
                    and (s.get("extra") or {}).get("opencode_message_id") == call["response_message_id"]]
        text = "\n".join(s.get("message", "") for s in matching).strip()
        if call["response"].strip() != text:
            raise ValueError("Response is not backed by its native message ID/text")
        actual_profiles={(s.get('extra') or {}).get('opencode_agent') for s in matching
                         if (s.get('extra') or {}).get('opencode_agent')}
        if actual_profiles and actual_profiles != {call['profile']}:
            raise ValueError('Native final response profile differs from the dispatched roster member')
        if not any(s.get("source") == "user" and s.get("message", "").strip() == call["prompt"].strip()
                   for s in child["steps"]):
            raise ValueError("Recipient did not receive the logged native prompt")
        child.setdefault("agent", {})["name"] = call["profile"]
    failed = [e for e in events if e.get("event") in {"group_failed", "call_failed"}]
    if failed:
        raise ValueError("Incomplete/failed Peer dispatch recorded; do not treat partial logs as a valid path")
    indexed = {}
    for message in [e for e in events if e.get("event") == "message"]:
        if hashlib.sha256(message["content"].encode()).hexdigest() != message["content_sha256"]:
            raise ValueError("Message content hash mismatch")
        if any(parent not in indexed for parent in message["parent_message_ids"]):
            raise ValueError("Missing or forward message provenance parent")
        if message["message_id"] in indexed:
            raise ValueError("Duplicate message identity")
        indexed[message["message_id"]] = message
    observations = {}
    for step in raw.get("steps", []):
        for result in (step.get("observation") or {}).get("results", []) or []:
            meta = ((result.get("extra") or {}).get("opencode_metadata") or {}).get("trustfork_peer")
            if meta:
                observations[meta["group_id"]] = {"content": str(result.get("content") or ""), "meta": meta,
                                                  "root_call_id": result["source_call_id"]}
    groups = []
    for done in [e for e in events if e.get("event") == "group_completed"]:
        gid = done["group_id"]
        messages = [e for e in indexed.values() if e["group_id"] == gid]
        obs = observations.get(gid)
        if obs is None:
            raise ValueError("No actual Main observation for a completed group")
        returned = [m for m in messages if m["receiver"] == "Main"]
        if len(returned) != 1 or obs["content"] != returned[0]["content"]:
            raise ValueError("Main received unexpected or truncated tool content")
        calls = [c for c in completed if c["group_id"] == gid]
        if not calls or returned[0]["content"] != calls[-1]["response"] or returned[0].get("native_message_id") != calls[-1]["response_message_id"]:
            raise ValueError("Main return is not the actual final native respondent")
        if obs["root_call_id"] != done["root_call_id"] or obs["meta"].get("returned_profile") != calls[-1]["profile"]:
            raise ValueError("Main return bound to wrong root call/actor")
        if any(k not in {"group_id", "kind", "returned_profile"} for k in obs["meta"]):
            raise ValueError("Unexpected root metadata could leak upstream material")
        if messages[0]["content"] != calls[0]["prompt"]:
            raise ValueError("Routed request differs from actual native prompt")
        mode = done["peer_mode"]
        source, recipient = done["source_profile"], done["recipient_profile"]
        if done["kind"] == "intake":
            expected = ([('Main', source), (source, recipient), (recipient, 'Main')]
                        if mode == "peer_chain" else [('Main', source), (source, 'Main')]
                        if mode == "direct" else [('Main', recipient), (recipient, 'Main')])
            if [(m["sender"], m["receiver"]) for m in messages] != expected:
                raise ValueError("Unexpected Peer intake communication path")
            if len(calls) != (2 if mode == "peer_chain" else 1):
                raise ValueError("Unexpected intake call count")
            if mode == "peer_chain":
                handoff = messages[1]
                if handoff["content"] != calls[0]["response"] or handoff["content"] not in calls[1]["prompt"]:
                    raise ValueError("Upstream response was not actually handed to recipient")
        elif len(calls) != 1 or [(m["sender"], m["receiver"]) for m in messages] != [('Main', calls[0]["profile"]), (calls[0]["profile"], 'Main')]:
            raise ValueError("Later authorization must dispatch only the Main-selected actor")
        groups.append({**done, "messages": messages, "calls": calls, "main_observation": obs})
    if not any(g["kind"] == "intake" for g in groups):
        raise ValueError("No completed Peer intake")
    changes = []
    for call in completed:
        if call['kind'] != 'intake':
            continue
        snapshots = {e['point']: e['snapshot'] for e in events if e.get('event')=='workspace_snapshot' and e.get('call_id')==call.get('call_id')}
        if set(snapshots) != {'before','after'} or not all(s.get('complete') for s in snapshots.values()):
            changes.append({'call_id':call.get('call_id'),'status':'unknown'})
        elif snapshots['before']['entries'] != snapshots['after']['entries']:
            changes.append({'call_id':call.get('call_id'),'status':'workspace_changed_during_advisory_intake'})
    return {"valid": True, "groups": groups, "actual_call_count": len(completed),
            "identity_definition_recorded": bool(definitions),
            "identity_definition_required": identity_required,
            "advisory_workspace_changes": changes,
            "main_messages": get_visible_messages(events, "Main"),
            "workspace_isolation": "shared workspace; complete information isolation is not claimed"}
