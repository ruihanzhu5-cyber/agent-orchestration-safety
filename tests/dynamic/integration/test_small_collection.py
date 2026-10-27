"""Four collection cells through real Docker/Pi and an explicit HTTP mock."""
import json,runpy,sys,importlib.metadata,base64,tarfile
from pathlib import Path
from trustfork.runtime.dynamic.common import repo_root,read_json,file_hash
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
from trustfork.tools.small_api_collection import CollectionRunner
from trustfork.agents.pi_dynamic import PiDynamic
from test_provider_history import MockHistory

def test_four_behaviors_are_frozen_before_failed_judge_and_fork_isolated(tmp_path,monkeypatch):
 import trustfork.tools.runtime_judge_review as review
 import trustfork.runtime.dynamic.provider as provider
 monkeypatch.setattr(provider,'real_http',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No external model network')))
 monkeypatch.setattr(review,'parent_sources',lambda p:({'synthetic-parent':'unchanged'},[]))
 sys.path.insert(0,str(repo_root()/'tests/dynamic/unit'))
 configured=runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_campaign_budget.py'))['configured_campaign']
 budget=CampaignBudget(tmp_path/'money.sqlite3',campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'identity_hash':'synthetic-old'})
 budget.reserve('old-paid',phase='engineering_smoke',reserved_cost_cny=1,metadata={});budget.submitted('old-paid');budget.settle('old-paid',settled_cost_cny=.5,usage={})
 migrate_attempts(budget.path,apply=True,backup=tmp_path/'before.sqlite3')
 attempt=ExecutionAttempt(budget,tmp_path/'attempt',attempt_id='collection-mock',parent_attempt='old',identity={'execution_code_sha':'synthetic-offline'})
 cfg=configured(budget.path);cfg['judge_binding']='deepseekflash';cfg['campaign_budget'].update(segment_id=budget.segment_id,segment_cny=20,segment_identity={'identity_hash':'synthetic-old'},must_exist=True)
 for b in cfg['logical_bindings'].values():b['capability']['tokenizer'].update(id='o200k_base',version=importlib.metadata.version('tiktoken'),count_method='local-message-content-and-schema-bpe-estimate')
 mock=MockHistory();runner=CollectionRunner(tmp_path/'parent',attempt,cfg,mode='mock',http_factory=lambda stage:mock)
 judge_calls=[]
 def failed_judge(*a,**k):judge_calls.append(1);return {'status':'failed','reason':'injected_extended_failure'}
 runner.formal=failed_judge
 class IsolationRuntime(PiDynamic):
  def _run_stage(self):
   if 'HP' in self.directory.parts:self.environment._worker('fs.write',{'path':'/workspace/offline-hp-only.txt','data':base64.b64encode(b'HP mock isolation marker').decode()},'offline-hp-isolation')
   elif 'HA' in self.directory.parts:assert not self.environment._worker('fs.exists',{'path':'/workspace/offline-hp-only.txt'},'offline-ha-isolation')['exists']
   return super()._run_stage()
 result=runner.collect(runtime_factory=IsolationRuntime)
 assert result['status']=='completed' and len(result['results'])==4 and not judge_calls
 assert [(x['protocol'],x['condition']) for x in result['results']]==[('S','HP'),('S','HA'),('F','HP'),('F','HA')]
 hashes={Path(v['path']):file_hash(Path(v['path'])) for v in result['results']}
 for protocol in ('S','F'):
  pair=[v for v in result['results'] if v['protocol']==protocol]
  assert pair[0]['checkpoint_id']==pair[1]['checkpoint_id']
  for row in pair:
   raw=read_json(Path(row['path']))
   with tarfile.open(raw['frozen_export']['workspace_tar']) as tar:assert any(n.endswith('offline-hp-only.txt') for n in tar.getnames())==(row['condition']=='HP')
   if protocol=='F':assert row['admitted_new_members']==[]
   else:assert row['admitted_new_members']==['C','D']
 assert runner.formal()['status']=='failed'
 assert hashes=={p:file_hash(p) for p in hashes} and read_json(runner.path/'behavior-results.json')['status']=='completed'
 before=len(mock.seen);again=runner.collect(runtime_factory=IsolationRuntime)
 assert again['status']=='completed' and len(mock.seen)==before and all(file_hash(p)==h for p,h in hashes.items())
 assert budget.segment_summary()['settled_cny']>=.5
 assert all(v['metadata'].get('execution_review_id')=='small-api-collection-20261027' for v in budget.rows() if v['request_id']!='old-paid')
 assert not list(runner.path.rglob('scoring_annotations.json')) and not list(runner.path.rglob('scores.json'))
