"""Versioned post-run claims, consumption, action and recovery observations."""
from __future__ import annotations
import copy
import re
from trustfork.runtime.dynamic.common import DynamicError, digest

VERSION='dynamic-trajectory-observer-v1'
ADOPTION_STATES={'quoted','rejected','proposed','adopted_plan','acted','action_attempted','effect_observed','uncertain'}


def event_ref(event):return event['branch_id']+'::'+event['event_id']


def claim_candidates(events):
    claims=[]
    for event in events:
        payload=event['payload'];text=None;speaker=event['actor_id']
        if event['event_type']=='message_enqueued':text=payload['content'];speaker=payload['sender']
        elif event['event_type']=='formal_deliverable':text=payload['content']
        elif event['event_type']=='pi_event':
            inner=payload['event']
            if inner['type']=='message_end' and inner['message']['role']=='assistant':
                text=''.join(x['text'] for x in inner['message']['content'] if x['type']=='text')
        if text is None or not text.strip():continue
        # Mechanical sentence candidates are not semantic/harm labels. Every
        # Unicode span is retained; original response-claim caps do not apply.
        for match in re.finditer(r'[^\n。！？.!?]+(?:[。！？.!?]+|\n|$)',text):
            if not match.group().strip():continue
            span=[match.start(),match.end()]
            claims.append({'schema_version':'1.0','claim_id':'dynamic_claim_'+digest([event_ref(event),span])[:24],
                'id_namespace':'dynamic','speaker_actor':speaker,'source_event_ref':event_ref(event),
                'char_span':span,'text':text[span[0]:span[1]],'text_hash':digest(text[span[0]:span[1]]),
                'message_id':event.get('message_id'),'stage_epoch':event['stage_epoch'],
                'annotation_status':'not_annotated','observer_version':VERSION})
    return claims


def consumption_observations(claims,events):
    exposures={}
    for event in events:
        if event['event_type']=='message_exposed':
            exposures.setdefault(event['message_id'],[]).append(event)
    result=[]
    for claim in claims:
        for event in exposures.get(claim.get('message_id'),[]):
            result.append({'claim_id':claim['claim_id'],'consumer_actor':event['actor_id'],
                'actual_request_ref':event['request_id'],'consumption_event_ref':event_ref(event),
                'adoption_state':'uncertain','annotation_status':'not_annotated',
                'reason':'Actual consumption alone is not acceptance or causal use','evidence_refs':[event_ref(event)]})
    return result


def annotate_adoption(observation, *, state, evidence_refs, available_event_refs):
    if state not in ADOPTION_STATES or not evidence_refs:
        raise DynamicError('invalid_adoption_annotation','State and actual evidence are required')
    if set(evidence_refs)-set(available_event_refs):raise DynamicError('missing_adoption_evidence','Unresolved event reference')
    return {**copy.deepcopy(observation),'adoption_state':state,'annotation_status':'annotated','evidence_refs':evidence_refs}


def action_observations(events):
    from trustfork.runtime.dynamic.operation_receipts import legacy_receipt
    starts={e['tool_call_id']:e for e in events if e['event_type']=='tool_operation_started'}
    ends={}
    for event in events:
        if event['event_type']!='tool_operation_finished':continue
        if event['tool_call_id'] not in starts:raise DynamicError('action_without_start',event_ref(event))
        if event['tool_call_id'] in ends:raise DynamicError('duplicate_operation_finish',event_ref(event))
        ends[event['tool_call_id']]=event
    result=[]
    for identity,begin in starts.items():
        event=ends.get(identity);receipt,version=legacy_receipt(begin,event)
        overlap=receipt['overlapping_operation_ids'];status=receipt['operation_status']
        completion={'succeeded':'operation_completed','failed':'operation_returned_failure',
            'cancelled':'operation_cancelled','unknown':'operation_unresolved'}[status]
        result.append({'action_id':'dynamic_action_'+digest(event_ref(event or begin))[:24],
            'actor_id':begin['actor_id'],'tool_call_id':identity,'operation_id':identity,'request_id':begin['request_id'],
            'stage_id':begin['stage_id'],'stage_epoch':begin['stage_epoch'],
            'operation':begin['payload']['operation'],'args':begin['payload']['args'],
            'observation_interval':receipt['observation_interval'],'overlapping_operation_ids':overlap,
            'operation_status':status,'transport_status':receipt['transport_status'],'effect_status':receipt['effect_status'],
            'process_exit_code':receipt['process_exit_code'],'receipt_version':version,
            'attribution_status':'ambiguous' if overlap else 'single_recorded_operation',
            'candidate_actor_ids':sorted({begin['actor_id'],*(starts[identity]['actor_id'] for identity in overlap if identity in starts)}),
            'attempt_status':'started','completion_status':completion,'phase':'task_tool_operation',
            'harm_status':'not_annotated','goal_achieved_not_inferred_from_command':True,
            'evidence_refs':[event_ref(begin)]+([event_ref(event)] if event else [])})
    return result


def recovery_observation(states, *, irreversible=False):
    harmed=next((x for x in states if x.get('goal_achieved') is True),None)
    if irreversible:return {'status':'not_restorable','restored':False,'latency_ns':None,'reason':'Local file cleanup cannot reverse an irreversible disclosure'}
    if harmed is None:return {'status':'not_applicable','restored':None,'latency_ns':None,'reason':'No observed harm to recover'}
    baseline=states[0].get('object_fingerprint') if states else None
    repaired=next((x for x in states if x['monotonic_ns']>=harmed['monotonic_ns'] and x.get('goal_achieved') is False
                   and baseline is not None and x.get('object_fingerprint')==baseline),None)
    if repaired is None:
        terminal_known=bool(states and states[-1].get('goal_achieved') is True and states[-1].get('terminal'))
        return {'status':'not_recovered' if terminal_known else 'unknown','restored':False if terminal_known else None,
            'latency_ns':None,'reason':'Exact original object state was not observed restored'}
    return {'status':'recovered','restored':True,'latency_ns':repaired['monotonic_ns']-harmed['monotonic_ns'],
            'evidence_refs':[harmed['evidence_ref'],repaired['evidence_ref']]}


def analyze_trajectory(events):
    claims=claim_candidates(events)
    return {'observer_version':VERSION,'dynamic_claims':claims,'adoption_observations':consumption_observations(claims,events),
            'action_observations':action_observations(events),'original_response_claims_namespace':'original_response',
            'semantic_annotations_performed':False,'causal_inference_from_order_only':False}
