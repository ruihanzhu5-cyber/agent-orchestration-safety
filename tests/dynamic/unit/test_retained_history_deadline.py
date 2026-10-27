from pathlib import Path
import copy,json,hashlib,pytest
from trustfork.runtime.dynamic.common import write_json,digest,canonical,DynamicError,file_hash
from trustfork.runtime.dynamic.retained_history_deadline import verify_deadline_task

def fixture(tmp_path):
 root=tmp_path/'history';(root/'control').mkdir(parents=True);archive=root/'state.tar';archive.write_bytes(b'synthetic frozen bytes')
 sessions={a:{'config':{'actor_id':a,'task_id':'p007'},'messages':[{'role':'assistant','stopReason':'aborted' if a=='B' else 'stop'}]} for a in ('Main','A','B')}
 events=[{'event_type':'model_request_ready','stage_id':s,'payload':{}} for s in ('fragment_1','fragment_2','fragment_3')]+[{'event_type':'history_execution_failed','stage_id':'initial','payload':{'code':'pi_turn_effect_unknown'}},{'event_type':'abnormal_state_frozen','stage_id':'fragment_3','payload':{}}]
 (root/'events.jsonl').write_bytes(b''.join(canonical(e)+b'\n' for e in events));frozen={'status':'frozen_export','workspace_tar':str(archive),'sha256':file_hash(archive)}
 record={'status':'failed_history_retained','termination_reason':'pi_turn_effect_unknown','task_id':'p007','budget':{'remaining_seconds':0,'attempts':[{'attempt_id':'last','actor_id':'B'}]},'session_hashes':{a:digest(s) for a,s in sessions.items()},'frozen_state':frozen,'request_ledger_hash':digest(events)}
 task={'record':record,'sessions':sessions};write_json(root/'task-completion.json',task);write_json(root/'history-execution.json',record)
 write_json(root/'partial-state.json',{'errors':[],'quiesce':{'status':'quiesced','active_at_deadline':[],'cancellations':[]},'freeze':{'status':'frozen'},'environment_export':frozen,'sessions':{a:{'status':'unknown' if a=='B' else 'observed'} for a in sessions}})
 (root/'control/rpc-inbound.spool').write_bytes(b'fully drained fixture')
 write_json(root/'control/transport-metrics.json',{'bridge_exit_code':0,'transport_failure':None,'reader_closed':True,'reader_alive':False,'processor_alive':False,'accepted_bytes':21,'persisted_bytes':21,'processed_bytes':21,'unpersisted_tail_bytes':0,'unprocessed_tail_bytes':0})
 (root/'control/network-guard.jsonl').write_bytes(b''.join(canonical({'actor_id':a,'operation':'close','guard':{'network_attempts':0,'blocked_host_fs':[],'blocked_host_exec':[]}})+b'\n' for a in sessions))
 requests=[{'request_id':'last','status':'charge_unknown','metadata':json.dumps({'actor_id':'B'})}]
 return root,task,requests

def test_deadline_carry_uses_final_hash_checked_aborted_session_and_keeps_unknown_fee(tmp_path):
 root,task,requests=fixture(tmp_path);before=file_hash(root/'task-completion.json');proof=verify_deadline_task(root,task,requests)
 assert proof['effective_history_status']=='budget_ended' and not proof['task_success_claimed'] and proof['new_model_requests']==0
 assert proof['earlier_partial_snapshot_statuses']['B']=='unknown' and proof['final_snapshots_complete']
 assert proof['unknown_provider_requests_retained']==['last'] and file_hash(root/'task-completion.json')==before
 assert requests[0]['status']=='charge_unknown' and task['record']['status']=='failed_history_retained'

@pytest.mark.parametrize('variant',['time-left','missing-actor','hash-mismatch','live-request','unknown-not-aborted','transport-tail','active-tool','changed-archive','guard'])
def test_deadline_carry_rejects_incomplete_unknown_or_non_deadline_source(tmp_path,variant):
 root,task,requests=fixture(tmp_path)
 if variant=='time-left':task['record']['budget']['remaining_seconds']=1
 elif variant=='missing-actor':task['sessions'].pop('B')
 elif variant=='hash-mismatch':task['sessions']['B']['messages'].append({'role':'user'})
 elif variant=='live-request':requests[0]['status']='submitted'
 elif variant=='unknown-not-aborted':task['sessions']['B']['messages'][-1]['stopReason']='toolUse';task['record']['session_hashes']['B']=digest(task['sessions']['B'])
 elif variant=='transport-tail':
  p=root/'control/transport-metrics.json';v=json.loads(p.read_text());v['unprocessed_tail_bytes']=1;write_json(p,v)
 elif variant=='active-tool':
  p=root/'partial-state.json';v=json.loads(p.read_text());v['quiesce']['active_at_deadline']=['pending'];write_json(p,v)
 elif variant=='changed-archive':(root/'state.tar').write_bytes(b'changed')
 else:(root/'control/network-guard.jsonl').write_text(json.dumps({'actor_id':'B','operation':'close','guard':{'blocked_host_fs':['trap']}})+'\n')
 with pytest.raises(DynamicError,match='history_deadline_not_reconciled'):verify_deadline_task(root,task,requests)

def test_new_stage_reconciles_bounded_carry_without_editing_parent_or_replaying_requests(tmp_path):
 from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
 from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
 from trustfork.runtime.dynamic.retained_history_deadline import register_deadline_carry
 root,task,requests=fixture(tmp_path);before=file_hash(root/'task-completion.json')
 b=CampaignBudget(tmp_path/'money.sqlite3',campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'origin':'original'})
 migrate_attempts(b.path,apply=True,backup=tmp_path/'before.sqlite3')
 parent=ExecutionAttempt(b,tmp_path/'parent',attempt_id='parent',parent_attempt='older',identity={'execution_code_sha':'old'})
 identity={'contract':'unchanged-history-generation'}
 parent.run('history/H2',identity,lambda:{'status':'failed_history_retained','path':str(root/'task-completion.json')},artifacts=lambda v:[root/'task-completion.json',root/'history-execution.json'])
 b.reserve('last',phase='engineering_smoke',reserved_cost_cny=.5,metadata={'actor_id':'B','execution_attempt_id':'parent','execution_stage_id':'history/H2'});b.submitted('last');b.settle('last')
 proof=verify_deadline_task(root,task,b.rows());proof['source_attempt']='parent'
 with b.tx() as db:old=dict(db.execute("SELECT * FROM execution_stages WHERE attempt_id='parent' AND stage_id='history/H2'").fetchone())
 child=ExecutionAttempt(b,tmp_path/'child',attempt_id='child',parent_attempt='parent',identity={'execution_code_sha':'new','history_deadline_continuation':proof})
 saved=register_deadline_carry(child,{'proof':proof,'task':task,'old_stage':old,'stage_identity':identity})
 assert saved['status']=='budget_ended' and saved['new_model_requests']==0
 again=child.run('history/H2',identity,lambda:pytest.fail('Must not regenerate any history'))
 assert again==saved
 derived=json.loads(Path(saved['path']).read_text())
 assert derived['record']['status']=='budget_ended' and derived['record']['deadline_reconciliation']['original_status']=='failed_history_retained'
 assert derived['sessions']==task['sessions'] and file_hash(root/'task-completion.json')==before
 assert parent.inspect()['stages'][0]['state']=='failed' and child.inspect()['stages'][0]['state']=='completed'
 assert b.rows()[0]['status']=='charge_unknown' and b.summary()['unsettled_reserved_cny']==.5
