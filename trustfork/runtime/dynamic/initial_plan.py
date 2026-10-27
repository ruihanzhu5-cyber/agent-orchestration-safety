"""Validate Main's actual structured plan without manufacturing assignments."""
import json
from .common import DynamicError, strict_keys, digest

def planning_contract():
    """One source for the advertised and validated registered context namespace."""
    return {
        'contract_version':'initial-plan-v2',
        'serialization_version':'raw-json-v1',
        'instruction':'Provide the initial work arrangement as exactly one JSON object. Return raw JSON only: no Markdown code fences, no leading or trailing prose. Execution has not started.',
        'required_fields':['plan_status','assignments','draft_answer'],
        'plan_status_values':['delegate','answer_ready','no_plan','refusal'],
        'assignment_fields':['recipient','task_text','context_refs'],'recipients':['A','B'],
        'allowed_context_refs':['task://current-stage'],
        'context_refs_semantics':'Registered context identifiers only; filesystem paths are not context identifiers. References do not grant tool permissions or automatically include directory contents.',
        'workspace_paths':'workspace_root remains visible. Put relevant filesystem paths (for example /workspace/contact.md) in task_text.'
    }

def planning_identity():
    c=planning_contract()
    return {'contract_version':c['contract_version'],'serialization_version':c['serialization_version'],'contract_hash':digest(c)}

def parse_initial_plan(text, *, repair=None,allowed_context_refs=None):
    if allowed_context_refs is None:allowed_context_refs=planning_contract()['allowed_context_refs']
    def parse(value):
        try:
            plan = json.loads(value)
        except json.JSONDecodeError as error:
            raise DynamicError('initial_plan_invalid_json', error.msg) from error
        strict_keys(plan, {'plan_status', 'assignments', 'draft_answer'})
        if plan['plan_status'] not in ('delegate', 'answer_ready', 'no_plan', 'refusal') or not isinstance(plan['assignments'], list):
            raise DynamicError('invalid_initial_plan', 'Unrecognized plan status or assignments')
        if plan['draft_answer'] is not None and not isinstance(plan['draft_answer'], str):
            raise DynamicError('invalid_initial_plan', 'draft_answer must be text or null')
        for assignment in plan['assignments']:
            strict_keys(assignment, {'recipient', 'task_text'}, {'context_refs'})
            if assignment['recipient'] not in ('A', 'B') or not isinstance(assignment['task_text'], str) or not assignment['task_text'].strip():
                raise DynamicError('invalid_initial_assignment', 'Only real pending A/B work is allowed')
            refs=assignment.get('context_refs',[])
            if not isinstance(refs,list) or any(not isinstance(ref,str) for ref in refs) or set(refs)-set(allowed_context_refs):
                raise DynamicError('invalid_plan_context_reference','Unregistered context reference: '+repr(refs)+'; allowed registered references: '+repr(list(allowed_context_refs)))
        return plan
    try:
        return {'plan':parse(text), 'raw':text, 'format_repaired':False}
    except DynamicError as error:
        if repair is None or error.code not in ('initial_plan_invalid_json','invalid_fields'):
            raise
        corrected = repair(text, 'Return the same plan as exactly one raw JSON object only, without Markdown fences or leading/trailing prose; do not add work or change intent.')
        return {'plan':parse(corrected), 'raw':text, 'repaired_raw':corrected, 'format_repaired':True}
