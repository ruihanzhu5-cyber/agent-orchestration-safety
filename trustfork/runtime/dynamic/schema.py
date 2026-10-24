"""Strict configuration and score states. Unknown values are errors."""
from __future__ import annotations

import math
from enum import StrEnum

from jsonschema import Draft202012Validator

from . import PROTOCOL_VERSION
from .common import DynamicError, strict_keys


class RunStatus(StrEnum):
    VALID = "valid_behavior"
    INFRA = "infra_error"
    PROTOCOL = "protocol_error"


class ScoreStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    NOT_ANNOTATED = "not_annotated"
    ERROR = "judge_error"


def validate_schema(value: dict, schema: dict) -> dict:
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        raise DynamicError("schema_validation_failed", errors[0].message,
                           evidence={"path": list(errors[0].path)})
    return value


def validate_bindings(config: dict, *, formal: bool) -> dict:
    strict_keys(config, {"protocol_version", "mode", "real_api_enabled", "logical_bindings", "judge_binding"}, {"note"})
    if config["protocol_version"] != PROTOCOL_VERSION:
        raise DynamicError("wrong_protocol", config["protocol_version"])
    if config["mode"] not in {"offline", "scripted-test", "api"}:
        raise DynamicError("invalid_mode", str(config["mode"]))
    if set(config["logical_bindings"]) != {"gpt4o", "deepseekflash"} or config["judge_binding"] != "gpt4o":
        raise DynamicError("invalid_model_aliases", "Only the two specified aliases and gpt4o judge are defined")
    required = {"provider", "base_url", "model_id", "key_env", "context_window", "max_output_tokens", "supported_parameters"}
    unresolved = []
    for alias, binding in config["logical_bindings"].items():
        strict_keys(binding, required)
        unresolved += [f"{alias}.{key}" for key in required if binding[key] is None]
        if binding["supported_parameters"] is not None and not isinstance(binding["supported_parameters"], list):
            raise DynamicError("invalid_supported_parameters", alias)
    if formal and (unresolved or config["real_api_enabled"] is not True):
        raise DynamicError("unresolved_formal_bindings", "Formal mode is not enabled or fully bound", evidence=sorted(unresolved))
    return {"unresolved": sorted(unresolved), "formal_ready": not unresolved and config["real_api_enabled"] is True}


def score_record(metric: str, value: float | None, status: str, reason: str | None = None,
                 evidence_refs: list | None = None, **metadata) -> dict:
    ScoreStatus(status)
    if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)):
        raise DynamicError("invalid_score", metric)
    if status == ScoreStatus.COMPLETE and value is None:
        raise DynamicError("complete_score_missing", metric)
    if status not in {ScoreStatus.COMPLETE, ScoreStatus.PARTIAL} and value is not None:
        raise DynamicError("missing_score_has_value", metric)
    return {"metric": metric, "value": value, "status": status, "reason": reason,
            "evidence_refs": evidence_refs or [], **metadata}
