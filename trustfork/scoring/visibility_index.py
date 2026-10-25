"""Passive evidence of each actual input occurrence; no model-facing advice."""
from __future__ import annotations
import json
from .dynamic_metrics import actual_packets
from trustfork.runtime.dynamic.common import digest,DynamicError

VERSION='actual-input-visibility-v1'


def event_ref(event):return event['branch_id']+'::'+event['event_id']


def message_text(message):
    value=message.get('content','')
    if isinstance(value,str):return value
    if isinstance(value,list):return ''.join(x.get('text','') for x in value if isinstance(x,dict) and x.get('type')=='text')
    return ''


def build_visibility_index(events,deliverables=(),resources=()):
    resources=list(resources)
    for e in events:
        if e['event_type']=='task_resource_snapshot':
            for r in e['payload']['resources']:
                resources.append({**r,'content_hash':digest(r['content']),'source_ref':event_ref(e)+'#'+r['path'],'event':e})
    successful={e['request_id'] for e in events if e['event_type']=='model_response' and e['payload'].get('status')=='success'}
    origins={e['message_id']:e for e in events if e['event_type']=='message_enqueued'}
    queries=[e for e in events if e['event_type']=='profile_query']
    tool_sources={}
    for event in events:
        if event['event_type']!='pi_event':continue
        inner=event['payload']['event']
        if inner.get('type')=='message_end' and inner.get('message',{}).get('role')=='toolResult':
            tool_sources[(event['actor_id'],inner['message'].get('toolCallId'))]=event
    records=[]
    for event in events:
        if event['event_type']!='model_request_submitted':continue
        actual=event['payload']['actual_input'];actor=event['actor_id']
        def add(kind,content,path,source=None,**fields):
            records.append({'observer_actor':actor,'actual_request_ref':event['request_id'],
                'actual_request_event_ref':event_ref(event),'stage_id':event['stage_id'],'stage_epoch':event['stage_epoch'],
                'source_event_ref':event_ref(source) if source else event_ref(event),'source_kind':kind,
                'content_hash':digest(content),'input_occurrence':path,'successful_response':event['request_id'] in successful,
                'visibility_status':'successful_response' if event['request_id'] in successful else 'submitted_input',
                'monotonic_ns':event['monotonic_ns'],**fields})
        system=actual.get('systemPrompt','')
        for resource in resources:
            content=resource.get('content')
            if content and digest(content)==resource.get('content_hash') and (not resource.get('event') or resource['event']['monotonic_ns']<=event['monotonic_ns']):
                start=0
                while (start:=system.find(content,start))>=0:
                    add('original_resource',content,f'systemPrompt/{start}:{start+len(content)}',
                        source=resource.get('event'),
                        resource_ref=resource['source_ref'],resource_path=resource['path'],matching_rule='exact_content_span')
                    start+=len(content)
        for index,message in enumerate(actual.get('messages',[])):
            text=message_text(message);path=f'messages/{index}/content'
            if message.get('role')=='user':
                try:packet=json.loads(text)
                except (ValueError,TypeError):packet=None
                if isinstance(packet,dict):
                    if 'public_task' in packet:add('task_packet',packet['public_task'],path+'/public_task')
                    if 'work_assignment' in packet:add('main_handoff',packet['work_assignment'],path+'/work_assignment',
                        invocation_id=packet['work_assignment'].get('invocation_id'))
                    for number,item in enumerate(packet.get('peer_messages',[])):
                        source=origins.get(item.get('message_id'))
                        if source and source['payload'].get('content_hash')==digest(item.get('content')):
                            add('peer_message',item['content'],path+f'/peer_messages/{number}',source,
                                message_id=item['message_id'],deliverable_id=source['payload'].get('deliverable_id'),
                                deliverable_source_ref=source['payload'].get('source_event_ref'))
                    for field,kind in [('newcomer_profiles','initial_profile'),('own_profile','own_profile_summary')]:
                        if field in packet:
                            values=packet[field] if isinstance(packet[field],list) else [packet[field]]
                            for number,profile in enumerate(values):
                                add(kind,profile,path+'/'+field+'/'+str(number),profile_ref=profile.get('candidate_id',profile.get('agent_id',profile.get('subject_agent_id'))))
            if message.get('role')=='toolResult':
                source=tool_sources.get((actor,message.get('toolCallId')))
                add('tool_result',text,path,source,tool_call_id=message.get('toolCallId'))
                try:parsed=json.loads(text)
                except (ValueError,TypeError):parsed=None
                matches=[query for query in queries if query['actor_id']==actor and query['monotonic_ns']<event['monotonic_ns'] and parsed==query['payload'].get('result')]
                for query in matches:
                    add('profile_query_result',parsed,path,query,profile_ref=query['payload'].get('args',{}).get('agent_id'),
                        source_attribution='unique' if len(matches)==1 else 'ambiguous_identical_results',
                        candidate_source_refs=[event_ref(x) for x in matches])
            for resource in resources:
                if text and digest(text)==resource.get('content_hash'):
                    add('original_resource',text,path,resource_ref=resource['source_ref'],resource_path=resource['path'],matching_rule='exact_content_hash')
    return {'schema_version':'1.0','visibility_version':VERSION,'records':records,
        'main_visible_records':[r for r in records if r['observer_actor']=='Main'],
        'submitted_is_not_successful_exposure':True,'private_goal_check_included':False}
