import json,subprocess
from pathlib import Path
import pytest
from trustfork.runtime.dynamic.first_api_plan import plan,judge_probe_cases,validate_probe_score,choose_judge,judge_cost_bounds
from trustfork.runtime.dynamic.common import DynamicError,repo_root
from trustfork.tools.first_dynamic_api import wire,phase_config

def test_fixed_plan_keeps_both_models_real_hp_ha_and_original_injections():
 rows=plan()
 assert len(rows)==12 and sum(r['kind']=='history' for r in rows)==4
 t3=[r for r in rows if r['kind']=='t3']
 assert {(r['team_model'],r['protocol'],r['condition']) for r in t3}=={(m,p,c) for m in ('gpt4o','deepseekflash') for p in ('S','F') for c in ('HP','HA')}
 assert all(r['q']=='C' and r['r']=='D' and r['original_benchmark_injections_retained'] for r in t3)
 assert all(r['q_goal_is_normal']==(r['condition']=='HP') for r in t3)

def test_five_judge_fixtures_require_facts_unknown_and_real_ids():
 cases=judge_probe_cases()
 assert len(cases)==5
 for case in cases:
  answer={'case_id':case['case_id'],'facts':{k:{'value':v,'evidence_refs':case['required_refs'][k]} for k,v in case['expected'].items()}}
  assert validate_probe_score(answer,case)['critical_pass']
  answer['facts']['effect']['evidence_refs']=['invented']
  with pytest.raises(DynamicError,match='judge_probe_evidence'):validate_probe_score(answer,case)

def test_selection_is_predeclared_and_does_not_guess_invoice_cost():
 a={'model':'gpt4o','critical_pass':True,'cost_cny':None,'cost_upper_cny':.4,'cost_lower_cny':.2,'latency_seconds':1}
 b={'model':'deepseekflash','critical_pass':True,'cost_cny':None,'cost_upper_cny':.3,'cost_lower_cny':.1,'latency_seconds':100}
 assert choose_judge([a,b])=={'selected':None,'reason':'actual_cost_order_unresolved_keep_both','dual_review':True}
 b['cost_upper_cny']=.05
 assert choose_judge([a,b])['selected']=='deepseekflash'
 b.update(critical_pass=False)
 assert choose_judge([a,b])['selected']=='gpt4o'
 a['critical_pass']=False
 assert choose_judge([a,b])['selected'] is None

def test_cache_and_peak_bounds_never_called_exact_bills():
 row={'status':'settled','usage':{'prompt_tokens':1000,'completion_tokens':500},'settled':30000}
 lo,hi=judge_cost_bounds([row],'deepseekflash')
 assert lo==pytest.approx(.00202) and hi==.006
 assert judge_cost_bounds([{**row,'status':'charge_unknown'}],'deepseekflash')==(None,None)

def test_probe_wire_deepseek_switch_gpt_clean_and_phase_copy():
 b={'model_id':'exact-model','base_url':'https://mock.invalid/v1','output_token_parameter':'max_tokens'}
 g=json.loads(wire(b,[],8192)['body'])
 assert not {'thinking','reasoning_effort'}&set(g)
 d=json.loads(wire({**b,'thinking':'enabled','reasoning_effort':'high'},[],16384)['body'])
 assert d['thinking']=={'type':'enabled'} and d['reasoning_effort']=='high' and 'temperature' not in d
 c={'campaign_budget':{'phase':'old'}}
 assert phase_config(c,'interface_probe')['campaign_budget']['phase']=='interface_probe' and c['campaign_budget']['phase']=='old'

def test_gitignore_only_allows_published_review_and_index(tmp_path):
 subprocess.run(['git','init','-q',str(tmp_path)],check=True)
 (tmp_path/'.gitignore').write_bytes((repo_root()/'.gitignore').read_bytes())
 paths=['runs/README.md','runs/published/first-api-20261026/README.md','runs/raw/session.json','nested/runs/raw/session.json','.env','runs/published/first-api-20261026/secrets.env','runs/published/first-api-20261026/debug.log']
 for name in paths:
  p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('test sentinel')
 def ignored(name):return subprocess.run(['git','check-ignore','--no-index','-q',name],cwd=tmp_path).returncode==0
 assert not ignored(paths[0]) and not ignored(paths[1])
 assert all(ignored(p) for p in paths[2:])
 subprocess.run(['git','add','runs/README.md','runs/published/first-api-20261026/README.md'],cwd=tmp_path,check=True)
 tracked=subprocess.check_output(['git','ls-files'],cwd=tmp_path,text=True).splitlines()
 assert tracked==paths[:2]

def test_account_rate_cost_bounds_use_returned_cache_and_offpeak_receipt_time():
 import datetime
 stamp=datetime.datetime(2026,10,26,19,tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp()
 row={'status':'settled','usage':{'prompt_tokens':1000,'completion_tokens':500,'prompt_cache_hit_tokens':100},'settled':6000,'submitted_at':stamp,'updated_at':stamp+2}
 lo,hi=judge_cost_bounds([row],'deepseekflash')
 assert lo<.002902<hi and hi-lo<.000003
 g={**row,'usage':{'prompt_tokens':1000,'completion_tokens':500,'prompt_tokens_details':{'cached_tokens':100}},'settled':26250}
 lo,hi=judge_cost_bounds([g],'gpt4o')
 assert lo<.0258125<hi and hi-lo<.000015
