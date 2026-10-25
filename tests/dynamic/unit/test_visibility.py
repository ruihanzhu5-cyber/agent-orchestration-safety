import copy
import json
from trustfork.runtime.dynamic.common import digest


def test_actual_successful_input_has_sources_and_no_main_peer_copy(known_trajectory):
    from trustfork.scoring.visibility_index import build_visibility_index
    result=build_visibility_index(known_trajectory['events'])
    messages=[r for r in result['records'] if r['source_kind']=='peer_message']
    assert len(messages)==1
    row=messages[0]
    assert row['observer_actor']=='A' and row['actual_request_ref']=='A-actual'
    assert row['message_id']=='m' and row['successful_response'] is True
    assert row['source_event_ref']==known_trajectory['ref'](known_trajectory['source'])
    assert not any(r['observer_actor']=='Main' and r.get('message_id')=='m' for r in result['records'])


def test_repeat_input_occurrences_are_retained_and_failed_submit_is_separate(known_trajectory):
    from trustfork.scoring.visibility_index import build_visibility_index
    events=copy.deepcopy(known_trajectory['events'])
    second=copy.deepcopy(known_trajectory['submitted']);second.update(event_id='new-submit',request_id='failed-A')
    events.append(second)
    records=[r for r in build_visibility_index(events)['records'] if r['source_kind']=='peer_message']
    assert len(records)==2 and len({r['actual_request_ref'] for r in records})==2
    assert [r['successful_response'] for r in records]==[True,False]
    assert all(r['input_occurrence'] for r in records)


def test_profile_query_cache_is_not_exposure_without_a_later_actual_input(known_trajectory):
    from trustfork.scoring.visibility_index import build_visibility_index
    events=copy.deepcopy(known_trajectory['events']);query=copy.deepcopy(events[-1])
    query.update(event_type='profile_query',event_id='query',actor_id='Main',request_id='query-request',message_id=None)
    query['payload']={'query':'get_public_profile','args':{'agent_id':'C'},'result':{'recorded_tasks':20}}
    query['monotonic_ns']=events[-1]['monotonic_ns']+1
    query['payload_hash']=digest(query['payload'])
    events.append(query)
    assert not any(r['source_kind']=='profile_query_result' for r in build_visibility_index(events)['records'])
    actual=copy.deepcopy(known_trajectory['submitted']);actual.update(event_id='next-input',actor_id='Main',request_id='Main-next')
    actual['payload']['actual_input']['messages']=[{'role':'toolResult','toolCallId':'profile-tool',
        'content':[{'type':'text','text':json.dumps(query['payload']['result'])}]}]
    actual['monotonic_ns']=query['monotonic_ns']+1;actual['payload_hash']=digest(actual['payload'])
    events.append(actual)
    row=next(r for r in build_visibility_index(events)['records'] if r['source_kind']=='profile_query_result')
    assert row['actual_request_ref']=='Main-next' and row['observer_actor']=='Main'
    assert row['successful_response'] is False


def test_tool_result_and_original_resource_source_have_separate_kinds(known_trajectory):
    from trustfork.scoring.visibility_index import build_visibility_index
    events=copy.deepcopy(known_trajectory['events'])
    actual=events[1]['payload']['actual_input']
    actual['messages'].append({'role':'toolResult','toolCallId':'read-original',
        'content':[{'type':'text','text':'Original IPI fixture bytes retained.'}]})
    events[1]['payload_hash']=digest(events[1]['payload'])
    inventory=[{'path':'/workspace/original.md','content_hash':digest('Original IPI fixture bytes retained.'),
        'source_ref':'original-asset://synthetic/fixture'}]
    kinds={r['source_kind'] for r in build_visibility_index(events,resources=inventory)['records']}
    assert {'tool_result','original_resource'} <= kinds


def test_identical_query_sources_do_not_create_extra_input_occurrences(known_trajectory):
    from trustfork.scoring.visibility_index import build_visibility_index
    base=known_trajectory['submitted'];queries=[]
    for i in range(2):
        q=copy.deepcopy(base);q.update(event_type='profile_query',event_id=f'query-{i}',actor_id='Main',request_id=f'query-r{i}',monotonic_ns=10+i)
        q['payload']={'query':'get_public_profile','args':{'agent_id':'C'},'result':{'records':[]}}
        q['payload_hash']=digest(q['payload']);queries.append(q)
    actual=copy.deepcopy(base);actual.update(actor_id='Main',event_id='actual-profile',request_id='after-queries',monotonic_ns=20)
    actual['payload']['actual_input']['messages']=[{'role':'toolResult','toolCallId':'q','content':[{'type':'text','text':'{"records": []}'}]}]
    rows=[r for r in build_visibility_index(queries+[actual])['records'] if r['source_kind']=='profile_query_result']
    assert len(rows)==1 and len(rows[0]['candidate_source_refs'])==2
    assert rows[0]['source_attribution'].startswith('ambiguous')


def test_future_reused_tool_id_cannot_rewrite_prior_result_provenance(known_trajectory):
    from trustfork.scoring.visibility_index import build_visibility_index
    actual=copy.deepcopy(known_trajectory['submitted']);actual.update(event_id='tool-input',actor_id='A',monotonic_ns=20)
    message={'role':'toolResult','toolCallId':'reused','content':[{'type':'text','text':'same result'}]}
    actual['payload']['actual_input']['messages']=[message]
    sources=[]
    for name,t in [('old',10),('future',30)]:
        source=copy.deepcopy(actual);source.update(event_type='pi_event',event_id=name,monotonic_ns=t)
        source['payload']={'event':{'type':'message_end','message':message}};sources.append(source)
    row=next(r for r in build_visibility_index(sources+[actual])['records'] if r['source_kind']=='tool_result')
    assert row['source_event_ref'].endswith('::old') and row['source_attribution']=='unique'
