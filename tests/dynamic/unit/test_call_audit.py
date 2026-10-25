import copy
from trustfork.tools.audit_model_calls import audit_request_events,audit_guard_records


def event(i,kind,payload):return {'branch_id':'synthetic-test-branch','event_id':str(i),'event_type':kind,'request_id':'r','payload':payload}


def test_actual_provider_events_override_false_zero_summaries_and_count_failed_attempts():
    # Pure in-memory records: no real transport, credential access, or request.
    submitted=event(1,'model_request_submitted',{'synthetic':False,'real_model_requests':0})
    failed=event(2,'model_response',{'response':{'provider':'synthetic-nonscripted-provider-fixture','stopReason':'error'}})
    judge=event(3,'judge_request_submitted',{'synthetic':False,'real_judge_requests':0})
    audit=audit_request_events([submitted,failed,judge,submitted])
    assert audit['real_model_calls_in_observed_scope']==1 and audit['real_judge_calls_in_observed_scope']==1
    assert audit['duplicate_event_records']==1


def test_missing_provider_and_conflicting_logs_never_become_zero():
    submitted=event(1,'model_request_submitted',{'synthetic':True})
    assert audit_request_events([submitted])['real_model_calls_in_observed_scope'] is None
    alternate=copy.deepcopy(submitted);alternate['payload']['synthetic']=False
    assert audit_request_events([submitted,alternate])['event_conflicts']


def test_scripted_attempts_and_guard_receipt_duplicates_are_separate_from_real_calls():
    submitted=event(1,'model_request_submitted',{'synthetic':True})
    response=event(2,'model_response',{'response':{'provider':'scripted'}})
    calls=audit_request_events([submitted,response]);assert calls['real_model_calls_in_observed_scope']==0
    assert calls['scripted_model_attempts']==1
    row={'rpc_id':'fixture','operation':'execute_turn','mode':'scripted-test','request_id':'r',
        'guard':{'network_attempts':1,'real_model_requests':0,'real_judge_requests':0}}
    guard=audit_guard_records([row,row])
    assert guard['unique_rpc_receipts']==1 and guard['positive_network_attempt_receipts']==1
    assert guard['initialized_real_request_counters_used_as_proof'] is False


def test_formal_aggregate_uses_actual_attempts_deduplicates_prefix_and_preserves_missing():
    from trustfork.scoring.aggregate_dynamic import call_summary
    record={'attempt_key':'prefix::r','kind':'model','classification':'real','provider':'synthetic-test-provider','evidence_ref':'prefix::e'}
    rows=[{'run_id':'a','real_model_requests':0,'actual_request_records':[record]},
        {'run_id':'b','real_model_requests':0,'actual_request_records':[record]}]
    assert call_summary(rows)['real_model_requests']==1
    assert call_summary(rows)['unique_actual_attempt_records']==1
    assert call_summary(rows+[{'run_id':'missing'}])['real_model_requests'] is None
