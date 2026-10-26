"""Actual Pi/Docker, injected HTTP mock, no credentials and no real sender."""
import json,runpy,importlib.metadata,threading,time
from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.runtime.dynamic.common import repo_root,digest
from test_provider_history import MockHistory

class WaitingMock(MockHistory):
 def __init__(self):super().__init__();self.rounds={}
 def __call__(self,url,body,key,timeout):
  value=json.loads(body);messages=value['messages']
  packet=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='user'))
  system=next(m['content'] for m in messages if m['role'] in ('system','developer'))
  if 'planning_contract' in packet:return super().__call__(url,body,key,timeout)
  with self.lock:self.seen.append(value)
  if system.startswith('Coordinate'):
   if packet['peer_messages']:delta={'content':'Synthetic final based on received work.'};finish='stop'
   else:
    delta={'tool_calls':[{'index':0,'id':'wait-'+str(len(self.seen)),'type':'function','function':{'name':'wait_for_update','arguments':json.dumps({'after_version':packet['coordination_version'],'timeout_seconds':3})}}]};finish='tool_calls'
  else:
   identity=packet.get('work_assignment',{}).get('invocation_id',digest(system))
   with self.lock:n=self.rounds.get(identity,0);self.rounds[identity]=n+1
   time.sleep(.03)
   if n<3:
    delta={'tool_calls':[{'index':0,'id':'work-'+str(len(self.seen)),'type':'function','function':{'name':'write','arguments':json.dumps({'path':'/workspace/wait-mock-'+str(n)+'.txt','content':'synthetic work '+str(n)})}}]};finish='tool_calls'
   else:delta={'content':'Synthetic completed work; no measured success.'};finish='stop'
  chunks=[{'choices':[{'index':0,'delta':delta,'finish_reason':None}]},{'choices':[{'index':0,'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}]
  return {'status':200,'headers':{'content-type':'text/event-stream'},'body':''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n'}

def test_main_wait_worker_progress_freeze_exposure_and_final_score(tmp_path,monkeypatch):
 # The only HTTP function is this explicit mock; any default transport is a test failure.
 import trustfork.runtime.dynamic.provider as provider
 monkeypatch.setattr(provider,'real_http',lambda *a,**k:(_ for _ in ()).throw(AssertionError('real transport forbidden')),raising=False)
 cfg=runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_provider_preparation.py'))['configuration']()
 for b in cfg['logical_bindings'].values():b['capability']['tokenizer'].update(id='o200k_base',version=importlib.metadata.version('tiktoken'),count_method='local-message-content-and-schema-bpe-estimate')
 mock=WaitingMock();t=ProviderTransport(cfg,mode='mock',journal=tmp_path/'requests.jsonl',http=mock,max_requests=60)
 r=PiDynamic('p001',tmp_path/'run',provider=t,protocol='S')
 prefix=r.run_prefix(ProviderSource())
 assert prefix['status']=='triggered'
 result=r.run_branch(prefix['checkpoint'],'HP',ProviderSource())
 assert result['run_status']=='valid_behavior'
 events=[json.loads(x) for x in (r.directory/'events.jsonl').read_text().splitlines()]
 waits=[e for e in events if e['event_type']=='actor_wait_registered' and e['actor_id']=='Main']
 assert waits
 # During each parked interval, no Main provider call is scheduled before a visible update.
 for start in waits:
  tail=[e for e in events if e['sequence']>start['sequence']]
  change=next((e for e in tail if e['event_type'] in ('message_enqueued','delegation_completed','delegation_started','delegation_released','actor_wait_ended')),None)
  if change:assert not any(e['actor_id']=='Main' and e['event_type']=='model_request_submitted' and e['sequence']<change['sequence'] for e in tail)
 assert sum(e['event_type']=='tool_operation_finished' for e in events)>=6
 exposed=[e for e in events if e['event_type']=='message_exposed' and e['actor_id']=='Main']
 assert exposed
 for e in exposed:
  req=next(x for x in events if x['request_id']==e['request_id'] and x['event_type']=='model_request_submitted')
  assert e['message_id'] in json.dumps(req['payload']['actual_input']) and req['sequence']<e['sequence']
 from trustfork.scoring.dynamic_pipeline import score_run
 summary=score_run(r.directory/'run.json',mode='test-fixtures')
 assert summary['run_id']==result['run_id']
 assert all(json.loads(x)['source']=='mock' for x in t.journal.read_text().splitlines())
