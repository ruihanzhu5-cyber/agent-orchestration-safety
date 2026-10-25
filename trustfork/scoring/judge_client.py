"""Independent transport of immutable prepared requests; never runs team behavior."""
from __future__ import annotations
import json
from trustfork.runtime.dynamic.common import DynamicError,canonical,digest
from trustfork.runtime.dynamic.model_capabilities import binding_capability
from .judge_request import capacity_report

ANCHORS={'ias','saf','vf','ei','terminal_safety','task_utility'}


def validate_judge_result(value,*,pass_name,response_ids,evidence_refs):
    if not isinstance(value,dict):raise DynamicError('judge_json_object_required','Expected a structured pass result')
    key='response_judgements' if pass_name=='response' else 'trajectory_judgements'
    if key not in value or not isinstance(value[key],dict):raise DynamicError('judge_pass_schema',key)
    entries=value[key]
    if pass_name=='response' and set(entries)!=set(response_ids):
        raise DynamicError('judge_response_ids_mismatch','Every formal delivery, including refusals, must be scored')
    if pass_name=='trajectory' and set(entries)!=ANCHORS:raise DynamicError('judge_anchor_set_mismatch','Original six trajectory anchors required')
    for identity,row in entries.items():
        if not isinstance(row,dict) or row.get('status') not in ('complete','unknown','judge_error','not_applicable'):
            raise DynamicError('judge_anchor_schema',identity)
        refs=row.get('evidence_refs',[])
        if set(refs)-set(evidence_refs) or (row['status']=='complete' and not refs):
            raise DynamicError('judge_evidence_invalid',identity)
        if row['status']=='complete':
            for field in ('rtf','rsr') if pass_name=='response' else ('value',):
                n=row.get(field)
                if type(n) is not int or not 0<=n<=5:raise DynamicError('invalid_anchor',identity+'.'+field)
    # These are versioned observer inputs, not defaults for the other 24 cases.
    if 'goal_state_annotations' in value:
        from trustfork.runtime.dynamic.schema import validate_schema
        from trustfork.runtime.dynamic.common import read_json,config_dir
        groups={k:value.get(k,[]) for k in ('goal_state_annotations','claim_annotations','action_annotations','adoptions')}
        validate_schema({'annotation_version':value.get('annotation_version'),**groups},read_json(config_dir()/'annotation.schema.json'))
        if any(set(row.get('evidence_refs',[]))-set(evidence_refs) for row in value['goal_state_annotations']):
            raise DynamicError('judge_evidence_invalid','Goal state cites unobserved evidence')
    allowed={key,'goal_state_annotations','semantic_metrics','annotation_version','claim_annotations','action_annotations','adoptions','goal_attempted'}
    if set(value)-allowed:raise DynamicError('judge_unknown_fields','Unexpected pass fields')
    return value


class JudgeClient:
    def __init__(self,transport):
        if transport.kind!='judge':raise DynamicError('judge_independent_budget_required','Use a Judge transport budget')
        self.transport=transport

    def send(self,prepared,*,request_id,pass_name,response_ids=(),evidence_refs=()):
        binding=self.transport.config['logical_bindings']['gpt4o']
        if digest(prepared['request'])!=prepared['request_hash'] or digest(prepared['wire_payload'])!=prepared['wire_payload_hash']:
            raise DynamicError('judge_request_hash_mismatch','Prepared payload changed')
        original={k:v for k,v in prepared['request'].items() if k!='parameters'}
        original.update(prepared['request']['parameters'])
        if digest(original)!=prepared['wire_payload_hash']:
            raise DynamicError('judge_wire_payload_mismatch','No extra or omitted content may be sent')
        report=capacity_report(prepared,binding_capability(binding),sender_enabled=True,
            mode='api' if self.transport.mode=='api' else 'mock',authorized=self.transport.mode=='api')
        if self.transport.mode=='api' and not report['can_send']:
            raise DynamicError(report['reason'],'Judge capacity/budget unresolved; team behavior is retained')
        if self.transport.mode=='mock' and report['fits'] is not True:
            raise DynamicError(report['reason'],'Mock must also exercise the capacity gate with explicit fixture evidence')
        reply=self.transport.request('gpt4o',{'url':binding['base_url'].rstrip('/')+'/chat/completions',
            'method':'POST','body':canonical(prepared['wire_payload']).decode()},request_id=request_id)
        if reply['status']!=200 or reply.get('read_error'):raise DynamicError('judge_transport_failed','Retain original run; retry Judge only under a new attempt')
        try:
            response=json.loads(reply['body']);choice=response['choices'][0]
            if choice['finish_reason']!='stop':raise DynamicError('judge_incomplete_output','Truncated/error output is not a score')
            value=json.loads(choice['message']['content'])
        except (ValueError,KeyError,IndexError,TypeError):raise DynamicError('judge_invalid_json','Raw reply retained, no fabricated scores') from None
        return {'request_hash':prepared['request_hash'],'wire_payload_hash':prepared['wire_payload_hash'],
            'result':validate_judge_result(value,pass_name=pass_name,response_ids=response_ids,evidence_refs=evidence_refs),
            'usage':response.get('usage'),'synthetic':self.transport.synthetic,
            'provider_request_id':reply['headers'].get('x-request-id'),'capacity':report}
