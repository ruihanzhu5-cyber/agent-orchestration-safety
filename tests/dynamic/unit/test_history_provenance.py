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


def test_preparation_counts_transport_interval_and_every_successful_load(tmp_path):
 import json
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from test_provider_preparation import configuration
 source=PiDynamic('p001',tmp_path/'source');h=History()
 for task in source.history_task_ids:h.add_task(task,{a:{'config':{'actor_id':a,'task_id':task},'messages':[]} for a in ('Main','A','B')},synthetic=True,status='refused')
 c=configuration();provider=ProviderTransport(c,mode='mock',journal=tmp_path/'actual-mock-journal.jsonl',http=lambda *a:{'status':200,'headers':{},'body':'{}'},max_requests=2)
 source.provider=provider
 wire={'url':'https://mock.invalid/v1/chat/completions','method':'POST','body':json.dumps({'model':'exact-fixture','messages':[{'role':'user','content':'synthetic transport accounting fixture'}],'max_tokens':1})}
 def prepare(**unused):provider.request('gpt4o',wire,request_id='history-only');return h.export()
 source.run_history=prepare;path=source.out/'history-bundle.json';bundle=prepare_history(source,None,path)
 assert bundle['accounting']['actual_provider_calls']['mock']==1
 provider.request('gpt4o',wire,request_id='later-suffix')
 target=PiDynamic('p024',tmp_path/'target');target.provider=provider
 load_history(target,path)
 assert (target.out/'history-bundle-reuse.jsonl').exists() and bundle['accounting']['actual_provider_calls']['mock']==1
