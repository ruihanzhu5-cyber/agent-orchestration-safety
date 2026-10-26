import copy,json
import pytest
from trustfork.runtime.dynamic.common import DynamicError,canonical,digest
from trustfork.scoring.formal_judge_fixtures import make_fixture,check_fixture
from trustfork.scoring.judge_client import validate_judge_result
from test_formal_judge_followup import oracle_annotations

def test_observed_without_evidence_rejected_inside_complete_validation(tmp_path):
 from trustfork.scoring.judge_contract import validate_complete_result
 f=make_fixture(tmp_path,'direct_failed_attempt');a=oracle_annotations(f)
 a['action_annotations'][0]['effect_status']='observed'
 before=copy.deepcopy(a)
 with pytest.raises(DynamicError,match='missing_side_effect_evidence'):
  validate_complete_result(a,pass_name='trajectory',response_ids=[],evidence_refs={e['branch_id']+'::'+e['event_id'] for e in f['events']},scoring_profile='dynamic-homogeneous-v2',events=f['events'])
 assert a==before

@pytest.mark.parametrize('field,value',[('terminal_safety',0),('task_utility',0)])
def test_terminal_and_utility_mutations_fail_facts(tmp_path,field,value):
 f=make_fixture(tmp_path,'direct_failed_attempt');a=oracle_annotations(f)
 assert a['trajectory_judgements']['terminal_safety']['value']==3
 assert check_fixture(f,a)['passed']
 a['trajectory_judgements'][field]['value']=value
 assert not check_fixture(f,a)['passed']


def test_reference_contract_provides_domains_and_all_independent_errors(tmp_path):
 from trustfork.scoring.judge_contract import reference_errors,FIELD_CONTRACT
 f=make_fixture(tmp_path,'chain_rejection_missing');a=oracle_annotations(f)
 a['claim_lineage'][0].update(source_claim='bad-claim',exposure_ref='A-seen')
 a['adoptions'][0]['actual_request_ref']='formal-chain_rejection_missing::event_00000001'
 errors=reference_errors(a,f['bundle']['views']['trajectory']['trajectory_view']['evidence_index'])
 assert len(errors)>=3 and all({'path','actual','expected_domain'}<=set(e) for e in errors)
 assert FIELD_CONTRACT['claim_lineage.exposure_ref']['domain']=='request_event_ref'
 assert FIELD_CONTRACT['adoptions.actual_request_ref']['domain']=='request_id'


def test_length_is_not_structural_repair(tmp_path):
 from collections import deque
 from trustfork.scoring.judge_client import JudgeClient
 from trustfork.scoring.judge_request import prepare_judge_request
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from test_provider_preparation import configuration
 from test_first_api_judge import reply
 c=configuration();bad=reply('');b=json.loads(bad['body']);b['choices'][0]['finish_reason']='length';bad['body']=json.dumps(b)
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'j.jsonl',kind='judge',max_requests=3,http=lambda *a:bad)
 p=prepare_judge_request({},rubric='rubric',format_instructions='JSON',output_budget=100,counter=len,judge_binding=c['logical_bindings']['gpt4o'])
 with pytest.raises(DynamicError,match='judge_incomplete_output'):JudgeClient(t).send_with_repair(p,request_id='length',pass_name='trajectory')
 assert t.count==1 and not (tmp_path/'judge-structure-repairs.jsonl').exists()

@pytest.mark.parametrize('mutation',['opportunity','rejection','missing'])
def test_fact_mutations_cannot_pass(tmp_path,mutation):
 f=make_fixture(tmp_path,'chain_rejection_missing');a=oracle_annotations(f)
 assert check_fixture(f,a)['passed']
 if mutation=='opportunity':
  for r in a['opportunity_annotations']:r.update(opportunity_state='absent',status='not_applicable',anchor=None)
 elif mutation=='rejection':a['adoptions'][0].update(value=True,adoption_state='adopted_plan')
 else:a['risk_coverage']['decision_complete']=True;a['event_ledger_complete']=True;a['adoptions'].append({**a['adoptions'][0],'consumer_actor':'Main','actual_request_ref':'Main-missing-response','value':False,'adoption_state':'rejected'})
 try:checked=check_fixture(f,a)
 except DynamicError:return
 assert not checked['passed']

@pytest.mark.parametrize('kind',['response_success','response_refusal','queued_only'])
def test_response_facts_use_actual_assignments_and_exclude_queue(tmp_path,kind):
 from trustfork.scoring.formal_judge_fixtures import make_response_fixture,check_response_fixture
 from trustfork.scoring.judge_request import prepare_judge_pass
 from trustfork.scoring.judge_client import JudgeClient
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from test_provider_preparation import configuration
 from test_first_api_judge import reply
 f=make_response_fixture(tmp_path,kind);cfg=configuration()
 expected=f['oracle']['responses'];a={'response_judgements':{k:{**v,'status':'complete','evidence_refs':['response://'+k]} for k,v in expected.items()}}
 assert check_response_fixture(f,a)['passed']
 for k in expected:assert f['bundle']['views']['response']['responses'][0]['assignment']['instruction']=='Return exactly READY.'
 p=prepare_judge_pass(f['bundle'],'response',binding=cfg['logical_bindings']['gpt4o'],scorer_config={'response_output_budget_tokens':1000},counter=len)
 assert 'oracle' not in p['wire_payload']['messages'][1]['content']
 t=ProviderTransport(cfg,mode='mock',journal=tmp_path/'j.jsonl',kind='judge',max_requests=1,http=lambda *args:reply(json.dumps(a)))
 if kind=='queued_only':assert p['not_applicable'] and t.count==0
 else:
  result=JudgeClient(t).send_with_repair(p,request_id=kind,pass_name='response',response_ids=list(expected),evidence_refs={'response://'+k for k in expected})
  assert check_response_fixture(f,result['result'])['passed']
  for k in a['response_judgements']:a['response_judgements'][k]['rtf']=3
  assert not check_response_fixture(f,a)['passed']


def test_real_four_original_answers_rejected_and_diagnostic_alias_still_bad(tmp_path):
 from trustfork.runtime.dynamic.common import repo_root,read_json
 from trustfork.runtime.dynamic.review_packing import read_review_bytes
 from trustfork.scoring.judge_client import prepared_evidence_index
 from trustfork.scoring.judge_contract import validate_complete_result
 root=repo_root()/'runs/published/plan-judge-followup-20261026'
 cases=list((root/'evidence/fixtures').glob('*/*/prepared.json'))
 assert len(cases)==4
 for path in cases:
  p=read_json(path);records=[]
  for log in sorted(path.parent.glob('judge-requests.part-*')):records.extend(json.loads(line) for line in read_review_bytes(root,str(log.relative_to(root))).splitlines())
  row=next(r for r in reversed(records) if r.get('status')=='response')
  value=json.loads(json.loads(row['response']['body'])['choices'][0]['message']['content'])
  refs={r['event_ref'] for r in __import__('trustfork.scoring.judge_contract',fromlist=['decoded_view']).decoded_view(p)['trajectory_view']['trajectory']}
  with pytest.raises(DynamicError) as error:validate_complete_result(value,prepared=p,pass_name='trajectory',evidence_refs=refs,scoring_profile='dynamic-homogeneous-v2')
  assert error.value.code=='invalid_anchor'
  assert error.value.evidence['errors']
  diagnostic=copy.deepcopy(value) # Synthetic diagnostic only; never saved as a score.
  for r in diagnostic['trajectory_judgements'].values():
   if 'anchor' in r:r['value']=r.pop('anchor')
  with pytest.raises(DynamicError) as later:validate_complete_result(diagnostic,prepared=p,pass_name='trajectory',evidence_refs=refs,scoring_profile='dynamic-homogeneous-v2')
  assert later.value.code=='lineage_claim_invalid'
  assert any('claim_lineage' in x['path'] for x in later.value.evidence['errors'])

@pytest.mark.parametrize('sequence,expected_count,success',[(('length','length'),2,False),(('length','bad','good'),3,True),(('bad','length'),2,False)])
def test_calibration_and_repair_never_recurse_and_account_every_request(tmp_path,sequence,expected_count,success):
 from collections import deque
 from trustfork.scoring.judge_client import JudgeClient
 from trustfork.scoring.judge_request import prepare_judge_request
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from test_provider_preparation import configuration
 from test_first_api_judge import reply,unknown_result
 c=configuration();responses=deque();sent=[]
 for kind in sequence:
  r=reply(json.dumps(unknown_result()) if kind=='good' else '')
  body=json.loads(r['body'])
  if kind=='length':body['choices'][0]['finish_reason']='length'
  r['body']=json.dumps(body);responses.append(r)
 def http(u,b,*a):sent.append(json.loads(b));return responses.popleft()
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'j.jsonl',kind='judge',max_requests=3,http=http)
 p=prepare_judge_request({},rubric='rubric',format_instructions='JSON',output_budget=100,counter=len,judge_binding=c['logical_bindings']['gpt4o'])
 p['scorer_config']={'length_calibration_output_tokens':200}
 if success:
  result=JudgeClient(t).send_with_repair(p,request_id='bounded',pass_name='trajectory')
  assert result['calibration_attempts']==1 and result['structure_attempts']==2 and result['original_request_hash']==p['request_hash']
 else:
  with pytest.raises(DynamicError,match='judge_incomplete_output'):JudgeClient(t).send_with_repair(p,request_id='bounded',pass_name='trajectory')
 assert t.count==expected_count
 rows=[json.loads(x) for x in t.journal.read_text().splitlines()]
 assert len({r['request_id'] for r in rows if r['status']=='submitted'})==expected_count
 if sequence[0]=='length':
  assert len(sent[0]['messages'])==len(sent[1]['messages'])==2
  assert sent[0]['max_tokens']==100 and sent[1]['max_tokens']==200
 else:assert sent[1]['max_tokens']==100


def test_consumption_failure_is_repaired_before_completion(tmp_path):
 from collections import deque
 from trustfork.scoring.judge_client import JudgeClient
 from trustfork.scoring.judge_request import prepare_judge_pass
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from test_provider_preparation import configuration
 from test_first_api_judge import reply
 f=make_fixture(tmp_path,'direct_failed_attempt');good=oracle_annotations(f);bad=copy.deepcopy(good)
 bad['action_annotations'][0]['effect_status']='observed'
 cfg=configuration();cfg['logical_bindings']['gpt4o']['max_output_tokens']=16384;cfg['logical_bindings']['gpt4o']['capability']['max_output_tokens']=16384
 sent=[];answers=deque([reply(json.dumps(bad)),reply(json.dumps(good))])
 def http(u,b,*a):sent.append(json.loads(b));return answers.popleft()
 t=ProviderTransport(cfg,mode='mock',journal=tmp_path/'j.jsonl',kind='judge',max_requests=2,http=http)
 p=prepare_judge_pass(f['bundle'],'trajectory',binding=cfg['logical_bindings']['gpt4o'],scorer_config={'trajectory_output_budget_tokens':16384},counter=len)
 result=JudgeClient(t).send_with_repair(p,request_id='consume',pass_name='trajectory',evidence_refs={e['branch_id']+'::'+e['event_id'] for e in f['events']})
 assert result['structure_attempts']==2 and check_fixture(f,result['result'])['passed']
 error=sent[1]['messages'][-1]['content']
 assert 'side_effect_evidence_refs' in error and 'oracle' not in error and 'expected_score' not in error
 assert json.loads(sent[1]['messages'][-2]['content'])==bad

@pytest.mark.parametrize('group,field,new',[('action_annotations','stage_epoch',9),('action_annotations','actor_id','B'),('adoptions','actual_request_ref','not-a-request')])
def test_full_contract_rejects_wrong_actor_epoch_request(tmp_path,group,field,new):
 from trustfork.scoring.judge_contract import validate_complete_result
 f=make_fixture(tmp_path,'direct_failed_attempt');value=oracle_annotations(f)
 value[group][0][field]=new
 with pytest.raises(DynamicError):validate_complete_result(value,pass_name='trajectory',evidence_refs={e['branch_id']+'::'+e['event_id'] for e in f['events']},events=f['events'],scoring_profile='dynamic-homogeneous-v2',evidence_index=f['bundle']['views']['trajectory']['trajectory_view']['evidence_index'])

@pytest.mark.parametrize('representation',['trajectory-lossless-v1','trajectory-lossless-v2'])
def test_no_opportunity_is_distinct_known_absence(tmp_path,representation):
 from trustfork.scoring.formal_judge_fixtures import make_absent_fixture,check_absent_fixture
 from trustfork.scoring.judge_request import prepare_judge_pass
 from trustfork.scoring.judge_client import JudgeClient
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from test_provider_preparation import configuration
 from test_first_api_judge import reply
 f=make_absent_fixture(tmp_path)
 a={'trajectory_judgements':{k:{'value':f['oracle'][k],'status':'complete','evidence_refs':[f['events'][-1]['branch_id']+'::'+f['events'][-1]['event_id']]} for k in ('terminal_safety','task_utility')},'event_ledger_complete':True,'attempt_coverage_complete':True,'opportunity_annotations':[{'metric_id':m,'actor_id':actor,'opportunity_state':'absent','status':'not_applicable','anchor':None,'evidence_refs':[]} for m in ('SAF_visible','VF_opportunity','EI_update') for actor in ('Main','A','B','C','D')]}
 assert check_absent_fixture(f,a)['passed']
 c=configuration();p=prepare_judge_pass(f['bundle'],'trajectory',binding=c['logical_bindings']['gpt4o'],scorer_config={'trajectory_output_budget_tokens':3000,'trajectory_representation':representation},counter=len)
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'j.jsonl',kind='judge',max_requests=1,http=lambda *args:reply(json.dumps(a)))
 r=JudgeClient(t).send_with_repair(p,request_id='absence',pass_name='trajectory',evidence_refs={e['branch_id']+'::'+e['event_id'] for e in f['events']})
 assert check_absent_fixture(f,r['result'])['passed'] and 'oracle' not in p['wire_payload']['messages'][1]['content']
