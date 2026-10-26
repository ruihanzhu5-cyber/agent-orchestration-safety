"""Strict configuration and score states. Unknown values are errors."""
from __future__ import annotations

import math
from functools import lru_cache
from enum import StrEnum

from jsonschema import Draft202012Validator

from . import PROTOCOL_VERSION
from .common import DynamicError, strict_keys


@lru_cache(maxsize=None)
def _contract_validator(name):
    from .common import config_dir,read_json
    schema=read_json(config_dir()/'contracts.schema.json')
    if name not in schema['$defs']:raise DynamicError('unknown_contract',name)
    selected={**schema,'$ref':'#/$defs/'+name}
    Draft202012Validator.check_schema(selected)
    return Draft202012Validator(selected)


def validate_contract(name,value):
    errors=sorted(_contract_validator(name).iter_errors(value),key=lambda error:str(error.path))
    if errors:raise DynamicError('schema_validation_failed',errors[0].message,evidence={'contract':name,'path':list(errors[0].path)})
    return value


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


def validate_bindings(config: dict, *, formal: bool, required_aliases=None, role_scope=None) -> dict:
    strict_keys(config, {"protocol_version", "mode", "real_api_enabled", "logical_bindings", "judge_binding"}, {"note","execution_limits","runtime_budgets","execution_scope","campaign_budget"})
    if config["protocol_version"] != PROTOCOL_VERSION:
        raise DynamicError("wrong_protocol", config["protocol_version"])
    if config["mode"] not in {"offline", "scripted-test", "api"}:
        raise DynamicError("invalid_mode", str(config["mode"]))
    if set(config["logical_bindings"]) != {"gpt4o", "deepseekflash"} or config["judge_binding"] not in {"gpt4o","deepseekflash"}:
        raise DynamicError("invalid_model_aliases", "Only the two specified aliases and candidate judges are defined")
    if role_scope=='judge':required_aliases={config['judge_binding']}
    active=set(config['logical_bindings']) if required_aliases is None else set(required_aliases)
    if not active or not active<=set(config['logical_bindings']):raise DynamicError('invalid_active_aliases','Unknown or empty role scope')
    required = {"provider", "base_url", "model_id", "key_env", "context_window", "max_output_tokens", "supported_parameters"}
    unresolved = []
    for alias, binding in config["logical_bindings"].items():
        strict_keys(binding, required, {'capability','api','compat','output_token_parameter','thinking','reasoning_effort','engineering_counting'})
        unresolved += [f"{alias}.{key}" for key in required if binding[key] is None]
        for key in ('api','compat','output_token_parameter'):
            if binding.get(key) is None:unresolved.append(alias+'.'+key)
        if binding.get('engineering_counting') not in (None,'deepseek-v41-text-v1'):raise DynamicError('request_counting_policy_unknown',alias)
        if binding.get('thinking') not in (None,'enabled','disabled'):raise DynamicError('invalid_thinking_mode',alias)
        if binding.get('reasoning_effort') not in (None,'high'):raise DynamicError('invalid_thinking_effort',alias)
        if alias=='gpt4o' and binding.get('thinking')=='enabled':raise DynamicError('invalid_thinking_mode','GPT4o cannot use DeepSeek thinking')
        for key in ('provider','base_url','model_id','key_env'):
            if binding[key] is not None and (not isinstance(binding[key],str) or not binding[key].strip()):
                raise DynamicError('invalid_model_binding',alias+'.'+key)
        for key in ('context_window','max_output_tokens'):
            value=binding[key]
            if value is not None and (not isinstance(value,int) or isinstance(value,bool) or value<=0):
                raise DynamicError('invalid_model_binding',alias+'.'+key)
        if binding["supported_parameters"] is not None and not isinstance(binding["supported_parameters"], list):
            raise DynamicError("invalid_supported_parameters", alias)
        if binding['supported_parameters'] is not None and (any(not isinstance(x,str) for x in binding['supported_parameters']) or
                len(set(binding['supported_parameters']))!=len(binding['supported_parameters'])):
            raise DynamicError('invalid_supported_parameters',alias)
        from .model_capabilities import binding_capability
        capacity=binding_capability(binding)
        if capacity['status']!='verified':unresolved.append(alias+'.effective_capacity')
        for key in ('effective_context_tokens','max_output_tokens','tokenizer','framing_tokens','output_token_parameter'):
            if capacity[key] is None:unresolved.append(alias+'.capability.'+key)
        if capacity['output_token_parameter'] and binding['supported_parameters'] is not None and capacity['output_token_parameter'] not in binding['supported_parameters']:
            unresolved.append(alias+'.capability.unsupported_output_parameter')
    all_unresolved=list(unresolved)
    unresolved=[x for x in unresolved if x.split('.')[0] in active]
    if not isinstance(config['real_api_enabled'],bool):raise DynamicError('invalid_real_api_flag','Expected boolean')
    if formal and (unresolved or config["real_api_enabled"] is not True):
        raise DynamicError("unresolved_formal_bindings", "Formal mode is not enabled or fully bound", evidence=sorted(unresolved))
    if formal and config['mode']!='api':raise DynamicError('invalid_formal_mode','Formal configuration must explicitly select API mode')
    return {"all_unresolved":sorted(all_unresolved),"active_aliases":sorted(active),"unresolved": sorted(unresolved), "formal_ready": not unresolved and config["real_api_enabled"] is True and config['mode']=='api'}


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
