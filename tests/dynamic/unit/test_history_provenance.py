from types import SimpleNamespace
import pytest
from trustfork.agents.pi_dynamic import PiDynamic
from trustfork.runtime.dynamic.history import History
from trustfork.runtime.dynamic.prepared_artifacts import prepare_history,load_history
from trustfork.runtime.dynamic.common import DynamicError
from trustfork.tools.audit_model_calls import audit_request_events
def test_history_original_journal_prefix_is_immutable_but_append_is_allowed(tmp_path):
 source=PiDynamic('p001',tmp_path/'history');h=History()
 for task in source.history_task_ids:h.add_task(task,{a:{'config':{'actor_id':a,'task_id':task},'messages':[]} for a in ('Main','A','B')},synthetic=True,status='refused')
 source.run_history=lambda **kw:h.export();log=tmp_path/'synthetic-history-journal.bin';log.write_bytes(b'original fixture evidence')
 source.provider=SimpleNamespace(mode='mock',journal=log)
 bundle=source.out/'history-bundle.json';prepare_history(source,None,bundle)
 target=PiDynamic('p024',tmp_path/'target');target.provider=SimpleNamespace(mode='mock',journal=log)
 log.write_bytes(log.read_bytes()+b' later T3 entries');assert load_history(target,bundle)['history_bundle_id']
 log.write_bytes(b'altered fixture evidence')
 with pytest.raises(DynamicError,match='history_ledger_prefix_changed'):load_history(target,bundle)
def test_interrupted_explicit_scripted_call_is_not_an_unresolved_real_call():
 event={'branch_id':'fixture','event_id':'e','event_type':'model_request_submitted','request_id':'r','payload':{'synthetic':True,'execution_backend':'scripted-test'}}
 result=audit_request_events([event]);assert result['real_model_calls_in_observed_scope']==0 and result['scripted_model_attempts']==1
