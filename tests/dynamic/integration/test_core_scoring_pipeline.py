"""Real Docker/Pi behavior plus separately validated mock core scoring, no model rerun."""
import json,sys,runpy,importlib.metadata
from pathlib import Path
from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.runtime.dynamic.prepared_artifacts import prepare_history,load_history
from trustfork.runtime.dynamic.common import repo_root,write_json,read_json,file_hash
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
from trustfork.tools.small_api_scoring import SmallScoringRunner
from trustfork.scoring.core_contract import CORE
from trustfork.scoring.dynamic_pipeline import load_events
from trustfork.scoring.dynamic_adapter import extract_formal_deliverables
from test_provider_history import MockHistory

def test_independent_core_real_pipeline_preserves_unscored_behavior_and_failed_extensions(tmp_path,monkeypatch):
 import trustfork.tools.runtime_judge_review as review
 import trustfork.runtime.dynamic.provider as provider
 monkeypatch.setattr(provider,'real_http',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Real network forbidden')))
 monkeypatch.setattr(review,'parent_sources',lambda p:({'synthetic-old-parent':'sealed'},[]))
 sys.path.insert(0,str(repo_root()/'tests/dynamic/unit'))
 configured=runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_campaign_budget.py'))['configured_campaign']
 money=tmp_path/'budget.sqlite3';b=CampaignBudget(money,campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'identity_hash':'old'})
 migrate_attempts(money,apply=True,backup=tmp_path/'backup.sqlite3')
 cfg=configured(money)
 # Synthetic accounting rates exercise sender/ledger flow, independently of provider prices.
 for limit in cfg['execution_limits'].values():limit['prices_per_million']['exact-fixture']={'input':.01,'output':.01}
 cfg['campaign_budget']['usd_to_cny_upper_bound']=1
 cfg['judge_binding']='deepseekflash';cfg['campaign_budget'].update(segment_id=b.segment_id,segment_cny=20,segment_identity={'identity_hash':'old'},must_exist=True)
 for binding in cfg['logical_bindings'].values():
  binding.update(context_window=1000000,max_output_tokens=131072);binding['capability'].update(effective_context_tokens=1000000,max_output_tokens=131072);binding['capability']['tokenizer'].update(id='o200k_base',version=importlib.metadata.version('tiktoken'),count_method='local-message-content-and-schema-bpe-estimate')
 mock=MockHistory();transport=ProviderTransport(cfg,mode='mock',journal=tmp_path/'model-requests.jsonl',http=mock,max_requests=120)
 hist=PiDynamic('p001',tmp_path/'history',provider=transport,team_model='deepseekflash');hpath=hist.out/'history-bundle.json';prepare_history(hist,ProviderSource(),hpath)
 behaviors=[];ids={};refs={}
 for protocol in ('S','F'):
  if protocol=='F':
   def fast(url,body,key,timeout):
    body_value=json.loads(body);packet=json.loads(next(v['content'] for v in reversed(body_value['messages']) if v['role']=='user'))
    if 'planning_contract' in packet:
     payload={'choices':[{'index':0,'delta':{'content':json.dumps({'plan_status':'answer_ready','assignments':[],'draft_answer':'Synthetic direct answer'})},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':20}}
     return {'status':200,'headers':{'content-type':'text/event-stream'},'body':'data: '+json.dumps(payload)+'\n\ndata: [DONE]\n\n'}
    return mock(url,body,key,timeout)
   transport.http=fast
  runtime=PiDynamic('p001',tmp_path/protocol,provider=transport,team_model='deepseekflash',protocol=protocol);history=load_history(runtime,hpath);prefix=runtime.run_prefix(ProviderSource(),history=history);assert prefix['status']=='triggered'
  run=runtime.run_branch(prefix['checkpoint'],'HP',ProviderSource());path=runtime.directory/'run.json';assert run['run_status']=='valid_behavior' and not (path.parent/'scoring').exists()
  tag='new-'+protocol+'-HP';events=load_events(path.parent,run);ids[tag]=[v['deliverable_id'] for v in extract_formal_deliverables(events,task_id='p001')];refs[tag]=events[-1]['branch_id']+'::'+events[-1]['event_id']
  behaviors.append({'case_id':'p001','team_model':'deepseekflash','protocol':protocol,'condition':'HP','behavior_status':'valid_behavior','behavior_execution_sha':'synthetic-behavior','path':str(path)})
 assert ids['new-S-HP'] and not ids['new-F-HP']
 before_calls=transport.count;source_hashes={Path(v['path']):file_hash(Path(v['path'])) for v in behaviors};behavior_dir=tmp_path/'behavior';write_json(behavior_dir/'behavior-results.json',{'phase':'collection_stopped','behavior_execution_sha':'synthetic-behavior','results':behaviors})
 judge_calls=[]
 for scenario in ('complete','response-gate-failed'):
  attempt=ExecutionAttempt(b,tmp_path/scenario,attempt_id='scoring-'+scenario,parent_attempt='collection',identity={'execution_code_sha':'synthetic-scoring'})
  runner=None
  def factory(stage):
   def http(url,body,key,timeout):
    judge_calls.append(stage);assert 'oracle' not in body
    if stage.startswith('calibration/'):
     contract,kind=stage.split('/')[1:];fixture=read_json(runner.path/'fixtures'/kind/'source.json')
     if contract!='trustfork-core-v1':answer={}
     elif fixture.get('pass_name')=='response':answer={'response_judgements':{k:{**v,'status':'complete','evidence_refs':['response://'+k]} for k,v in fixture['oracle']['responses'].items()}}
     else:answer={'trajectory_judgements':{k:{'value':fixture['oracle'][k],'status':'unknown' if fixture['oracle'][k] is None else 'complete','evidence_refs':[] if fixture['oracle'][k] is None else [fixture['events'][-1]['branch_id']+'::'+fixture['events'][-1]['event_id']]} for k in ('terminal_safety','task_utility')}}
    else:
     tag,name=stage.rsplit('/',2)[-2:]
     answer={'response_judgements':{k:{'rtf':1,'rsr':0,'status':'complete','evidence_refs':['response://'+k]} for k in ids[tag]}} if name=='response' else {'trajectory_judgements':{k:{'value':n,'status':'complete','evidence_refs':[refs[tag]]} for k,n in [('terminal_safety',3),('task_utility',2)]}}
    return {'status':200,'headers':{'content-type':'application/json'},'body':json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}],'usage':{'prompt_tokens':100,'completion_tokens':20}})}
   return http
  runner=SmallScoringRunner(tmp_path/'parent',attempt,cfg,behavior_dir,mode='mock',http_factory=factory);gates=runner.calibrate(CORE)['gates'];assert all(gates.values())
  if scenario=='response-gate-failed':gates['response']=False
  for row in behaviors:
   tag='new-'+row['protocol']+'-HP';result=runner.score_source(Path(row['path']),tag,'synthetic-behavior',gates)
   assert result['metrics']['scores']['TH']['value']==40 and result['metrics']['scores']['TUL']['value']==60
   if scenario=='response-gate-failed':assert result['pass_states']['response']['status']=='not_started' and result['metrics']['scores']['RTF']['value'] is None
   elif row['protocol']=='F':assert result['pass_states']['response']['status']=='not_applicable' and result['metrics']['scores']['RTF']['value'] is None
   else:assert result['metrics']['scores']['RTF']['value']==20
  ext=runner.calibrate('dynamic-extended-v2');assert not ext['gates']['trajectory']
  snapshots={v['path']:file_hash(Path(v['path'])) for v in behaviors};assert all(snapshots[str(p)]==h for p,h in source_hashes.items())
  assert transport.count==before_calls and all(not (p.parent/'scoring').exists() for p in source_hashes)
  prior=len(judge_calls);runner.calibrate(CORE);assert len(judge_calls)==prior
 assert len(judge_calls)<=48 and all(v['metadata'].get('kind')=='judge' for v in b.rows() if v['metadata'].get('small_api_judge_group_id'))
