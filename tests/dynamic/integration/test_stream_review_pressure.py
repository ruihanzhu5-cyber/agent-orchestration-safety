"""120 real Pi turns with incremental SSE HTTP mock; no model network."""
import json,runpy,importlib.metadata,resource
from trustfork.runtime.dynamic.common import repo_root,write_json
from trustfork.runtime.dynamic.pi_client import PiClient
from trustfork.runtime.dynamic.events import EventLedger
from trustfork.runtime.dynamic.provider import ProviderTransport

def test_120_pi_turns_incremental_reasoning_text_and_tool_arguments(tmp_path,monkeypatch):
 import trustfork.runtime.dynamic.provider as module
 monkeypatch.setattr(module,'real_http',lambda *a,**k:(_ for _ in ()).throw(AssertionError('real network forbidden')))
 cfg=runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_provider_preparation.py'))['configuration']()
 cfg['execution_scope']='engineering_smoke'
 for alias,b in cfg['logical_bindings'].items():
  b['capability']['tokenizer'].update(id='o200k_base',version=importlib.metadata.version('tiktoken'),count_method='local-message-content-and-schema-bpe-estimate')
  b['capability']['status']='declared';b.update(thinking='enabled' if alias=='deepseekflash' else 'disabled',reasoning_effort='high' if alias=='deepseekflash' else None)
  if alias=='deepseekflash':b['compat'].update(supportsReasoningEffort=True,requiresReasoningContentOnAssistantMessages=True)
  b['supported_parameters']+=['thinking','reasoning_effort']
 def http(url,body,key,timeout):
  frames=[]
  def delta(value):frames.append({'choices':[{'index':0,'delta':value,'finish_reason':None}]})
  for i in range(8):delta({'reasoning_content':'Synthetic thought '+str(i)+'; '})
  for i in range(8):delta({'content':'Synthetic text '+str(i)+'; '})
  delta({'tool_calls':[{'index':0,'id':'call-directory','type':'function','function':{'name':'get_team_directory','arguments':''}}]})
  for part in ['{','}']:delta({'tool_calls':[{'index':0,'function':{'arguments':part}}]})
  frames.append({'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}})
  return {'status':200,'headers':{'content-type':'text/event-stream'},'body':''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n'}
 transport=ProviderTransport(cfg,mode='mock',journal=tmp_path/'requests.jsonl',http=http,max_requests=120)
 ledger=EventLedger(tmp_path/'events.jsonl','stream-120','p001')
 client=PiClient(tmp_path/'control',None,ledger=ledger,provider=transport,model_refs={'Main':'deepseekflash'},coordination=lambda *a:{'version':0,'members':[]})
 observations=[]
 try:
  session,_=client.create_session('Main',branch_id='stream-120',task_id='p001',system_prompt='Synthetic Main')
  for i in range(120):
   result=client.call(session,'execute_turn',{'messages':[{'role':'user','content':'Synthetic turn '+str(i),'timestamp':i+1}],'max_output_tokens':512},request_id='stream-'+str(i),timeout=60)
   assert result['status']=='success'
   assert result['bridge_metrics']['audit_cache_before_turn']=={'events':0,'inputs':0}
   assert any(e['type']=='message_update' for e in result['events'])
   assert result['bridge_metrics']['audit_events_cached']<200
   observations.append(result['bridge_metrics'])
  assert not hasattr(client,'actual_inputs') and not client.request_deadlines
 finally:client.close()
 assert transport.count==120
 assert sum(1 for _ in ledger.iter_events(event_type='model_request_submitted'))==120
 assert sum(1 for _ in ledger.iter_events(event_type='pi_event'))>120*20
 stats=json.loads((tmp_path/'control/transport-metrics.json').read_text())
 assert stats['unprocessed_tail_bytes']==0 and stats['accepted_bytes']==stats['persisted_bytes']==stats['processed_bytes']
 assert stats['bridge_exit_code']==0
 write_json(tmp_path/'resource-measurement.json',{'version':'stream-review-resource-v1','turns':120,'synthetic':True,'real_model_calls':0,'node_first':observations[0],'node_last':observations[-1],'node_peak_rss_bytes':max(v['rss_bytes'] for v in observations),'python_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'ledger':ledger.memory_stats(),'events_bytes':ledger.path.stat().st_size,'rpc':stats,'limitation':'Legitimate Pi session context grows; only audit caches/queues are bounded.'})
