"""Offline complete-payload measurements; no provider SDK or network sender."""
import argparse,json
from pathlib import Path
from trustfork.runtime.dynamic.common import read_json,write_json,digest,canonical
from trustfork.runtime.dynamic.model_capabilities import unknown_capability
from trustfork.scoring.dynamic_adapter import judge_prompts
from trustfork.scoring.trajectory_codec import encode_trajectory,decode_trajectory,VERSION
from trustfork.scoring.judge_request import prepare_judge_request,capacity_report,offline_counter


def long_fixture():
    text='Original resource/原始材料🙂\n'+''.join(f'line{i}: exact data value={i*i}\n' for i in range(1200))
    history=[];events=[]
    for epoch in range(6):
        for turn in range(12):
            history.append({'role':'toolResult','content':[{'type':'text','text':text}],'bytes_base64':'//4AAQ=='})
            events.append({'event_ref':f'fixture::{epoch}-{turn}','event_type':'model_request_submitted',
                'actor_id':'ABCD'[turn%4],'stage_id':f'fixture-stage-{epoch}','stage_epoch':epoch,
                'payload':{'actual_input':{'messages':list(history),'systemPrompt':'Public fixture only'},'request_id':f'r{epoch}-{turn}'}})
        history=[]
    return {'private_goals_removed':True,'task':{'purpose':'Synthetic long multi-stage engineering fixture, not a research card'},
        'trajectory':events,'workspace_after':{},'final_response':'fixture final'}


def volume_breakdown(view,counter):
    """Overlapping structural views, never additive attribution or harm labels."""
    groups={k:[] for k in ('system_prompts','request_histories','request_snapshots','tool_results',
        'tool_schemas','profile_material','tool_operation_events','ordered_events','workspace_after')}
    for event in view.get('trajectory',[]):
        groups['ordered_events'].append(event)
        if event.get('event_type') in ('tool_operation_started','tool_operation_finished'):groups['tool_operation_events'].append(event)
        if event.get('event_type')=='main_profiles_exposed':groups['profile_material'].append(event['payload'].get('profiles'))
        if event.get('event_type')!='model_request_submitted':continue
        actual=event['payload']['actual_input'];groups['request_snapshots'].append(actual)
        groups['system_prompts'].append(actual.get('systemPrompt',''));groups['tool_schemas'].append(actual.get('tools',[]))
        groups['request_histories'].append(actual.get('messages',[]))
        for message in actual.get('messages',[]):
            if message.get('role')=='toolResult':groups['tool_results'].append(message)
            if message.get('role')!='user':continue
            text=message.get('content','')
            if isinstance(text,list):text=''.join(x.get('text','') for x in text if isinstance(x,dict))
            try:packet=json.loads(text)
            except (TypeError,ValueError):continue
            if isinstance(packet,dict):
                for key in ('newcomer_profiles','own_profile'):
                    if key in packet:groups['profile_material'].append(packet[key])
    if 'workspace_after' in view:groups['workspace_after'].append(view['workspace_after'])
    result={}
    for name,values in groups.items():
        unique={digest(v):v for v in values}
        result[name]={'occurrences':len(values),'exact_unique_values':len(unique),
            'tokens_of_category_serialization':counter(canonical(values).decode()),
            'tokens_of_unique_category_serialization':counter(canonical(list(unique.values())).decode()),
            'exact_duplicate_occurrences':len(values)-len(unique)}
    return {'categories':result,'categories_overlap':True,'do_not_sum_categories':True,
        'method':'Independent canonical category serializations; BPE boundaries and nested structures overlap. Repetition is exact-hash only.'}


def audit_view(view,*,label,diagnostic_output_reserve=4096):
    packed=encode_trajectory(view);assert decode_trajectory(packed)==view
    rubric=judge_prompts([])['trajectory']; counter=offline_counter();measure={}
    for name,value in [('legacy-full',view),(VERSION,packed)]:
        p=prepare_judge_request(value,rubric=rubric,format_instructions='Return original rubric anchors and evidence references as JSON.',
            output_budget=diagnostic_output_reserve,representation=name)
        measure[name]={'view_tokens':counter(canonical(value).decode()),'full_prepared_input_tokens':p['input_tokens'],
            'wire_serialization_tokens':p['wire_serialization_tokens'],'wire_tokens_are_model_input_tokens':False,
            'diagnostic_output_reserve':diagnostic_output_reserve,'reference_128000_fits':p['input_tokens']+diagnostic_output_reserve<=128000,
            'reference_128000_excess_tokens':max(0,p['input_tokens']+diagnostic_output_reserve-128000),
            'rubric_tokens_separate':p['rubric_tokens_separate'],'format_instruction_tokens_separate':p['format_instruction_tokens_separate'],
            'codec_instruction_tokens_separate':p['codec_instruction_tokens_separate'],
            'prepared_content_and_schema_delta_tokens':p['input_tokens']-counter(canonical(value).decode()),
            'wire_serialization_extra_tokens_not_model_text':p['wire_serialization_tokens']-p['input_tokens'],
            'request_hash':p['request_hash'],'capacity':capacity_report(p,unknown_capability()),'tokenizer':p['tokenizer']}
    return {'label':label,'source_hash':digest(view),'decoded_hash':digest(decode_trajectory(packed)),
        'roundtrip_exact':True,'event_count':len(view.get('trajectory',[])),'pool_entries':len(packed['content_pool']),
        'measurements':measure,'volume_breakdown':volume_breakdown(view,counter),
        'cognitive_equivalence':'requires future real discovery comparison; not established offline'}


def audit_frozen_prepared(prepared,binding):
    """Compare identical decoded evidence, original v1 and optional prefix v2; no sender."""
    from collections import Counter
    from trustfork.scoring.trajectory_codec import encode_trajectory_v2,PREFIX_VERSION,PREFIX_INSTRUCTIONS,INSTRUCTIONS
    from trustfork.runtime.dynamic.token_accounting import engineering_counting_policy,count_request
    import copy
    original=prepared['wire_payload'];old=json.loads(original['messages'][1]['content'])
    decoded=decode_trajectory(old) if old.get('representation_version') else old
    view=decoded.get('trajectory_view',decoded);events=view.get('trajectory',[])
    kinds=Counter();subtypes=Counter();partial_equal=0;updates=0;prefix_pairs=0;previous={}
    for e in events:
        kinds[e['event_type']]+=len(canonical(e))
        if e['event_type']!='pi_event':continue
        inner=e['payload'].get('event',{});subtypes[inner.get('type','unknown')]+=len(canonical(e))
        if inner.get('type')!='message_update':continue
        updates+=1;partial=inner.get('assistantMessageEvent',{}).get('partial')
        partial_equal+=int(partial is not None and partial==inner.get('message'))
        # Prefix identity refers to the same actor, request and content block.
        for index,block in enumerate(inner.get('message',{}).get('content',[])):
            if not isinstance(block,dict):continue
            for field in ('text','thinking','partialArgs'):
                text=block.get(field)
                if not isinstance(text,str):continue
                key=(e.get('actor_id'),e.get('request_id'),index,field)
                before=previous.get(key)
                if before and text.startswith(before) and text!=before:prefix_pairs+=1
                previous[key]=text
    policy=engineering_counting_policy(binding);measure={}
    base_system=original['messages'][0]['content']
    for instruction in (PREFIX_INSTRUCTIONS,INSTRUCTIONS):
        suffix='\n\n'+instruction
        if base_system.endswith(suffix):
            base_system=base_system[:-len(suffix)];break
    for name,body in [('legacy-full',decoded),('trajectory-lossless-v1',encode_trajectory(decoded)),(PREFIX_VERSION,encode_trajectory_v2(decoded))]:
        wire=copy.deepcopy(original);wire['messages'][1]['content']=canonical(body).decode()
        wire['messages'][0]['content']=base_system
        if name in ('trajectory-lossless-v1',PREFIX_VERSION):wire['messages'][0]['content']+='\n\n'+(PREFIX_INSTRUCTIONS if name==PREFIX_VERSION else INSTRUCTIONS)
        a=count_request(wire,policy);byte_binding=copy.deepcopy(binding);byte_binding.pop('engineering_counting',None)
        ba=count_request(wire,engineering_counting_policy(byte_binding))
        n=a['estimated_total_input_tokens']
        measure[name]={'view_utf8_bytes':len(canonical(body)),'decoded_wire_message_utf8_bytes':sum(len(m['content'].encode()) for m in wire['messages']),
          'byte_estimate':ba['input_tokens'],'token_estimate':a['input_tokens'],'tokenizer':a['tokenizer'],'service_prompt_tokens':None,
          'framing_tokens':a['framing_tokens'],'safety_margin_tokens':max(2048,(n+9)//10),'wire_payload_hash':digest(wire),'roundtrip_exact':True}
    return {'source_view_hash':digest(decoded),'sanitized_view_hash':digest(view),'source_prepared_request_hash':prepared['request_hash'],
       'measurements':measure,'event_type_utf8_bytes':dict(kinds),'pi_subtype_utf8_bytes':dict(subtypes),
       'event_count':len(events),'message_update_count':updates,'partial_equals_message':partial_equal,'growing_string_prefix_pairs':prefix_pairs,
       'index_counts':{k:len(v) for k,v in view.get('evidence_index',{}).items() if isinstance(v,list)},
       'independent_compartments_utf8_bytes':{'trajectory':len(canonical(events)),'evidence_index':len(canonical(view.get('evidence_index',{}))),
        **{k:len(canonical(v)) for k,v in decoded.items() if k!='trajectory_view'}},
       'nonadditive_diagnostics':True,'service_usage_unknown_for_unsent_requests':True,'no_source_mutation':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--include-long-fixture',action='store_true');a=p.parse_args();rows=[]
    for path in sorted(a.input.rglob('trajectory_input.json')):
        if any(x in ('versions','legacy') for x in path.relative_to(a.input).parts):continue
        envelope=read_json(path);view=envelope.get('data',envelope)
        if 'content_hash' in envelope and envelope['content_hash']!=digest(view):raise ValueError('Input hash changed')
        rows.append(audit_view(view,label=path.relative_to(a.input).as_posix()))
    if a.include_long_fixture:rows.append(audit_view(long_fixture(),label='synthetic-six-stage-long-fixture'))
    report={'version':'judge-input-audit-v1','mode':'offline','real_api_enabled':False,'sender_present':False,
        'reference_capacity_tokens':128000,'reference_is_actual_route_evidence':False,
        'reference_assumes_zero_additional_provider_framing':True,
        'reserve_4096_is_diagnostic_not_frozen_judge_budget':True,'provider_framing':'unknown; all actual routes blocked',
        'rows':rows,'formal_ready':False}
    write_json(a.out,report)
    print(json.dumps({'rows':len(rows),'exact_roundtrips':sum(r['roundtrip_exact'] for r in rows),'formal_ready':False}))


if __name__=='__main__':main()
