import copy,pytest
from trustfork.runtime.dynamic.common import digest,DynamicError
from trustfork.scoring.dynamic_pipeline import judge_pass_binding

def test_explicit_new_scoring_binding_keeps_legacy_origin_and_rejects_tamper():
 old={'model_id':'old-judge'};new={'model_id':'new-judge','provider':'official','base_url':'https://example.invalid'}
 m={'judge_binding_identity_version':'judge-binding-snapshot-v1','resolved_judge_binding':new,'resolved_judge_binding_hash':digest(new)}
 assert judge_pass_binding({},old)==old
 assert judge_pass_binding(m,old)==new and old=={'model_id':'old-judge'}
 bad=copy.deepcopy(m);bad['resolved_judge_binding']['model_id']='tampered'
 with pytest.raises(DynamicError,match='annotation_judge_binding_invalid'):judge_pass_binding(bad,old)
 for bad in ({'resolved_judge_binding_hash':'incomplete'},dict(m,judge_binding_identity_version='unknown')):
  with pytest.raises(DynamicError,match='annotation_judge_binding_invalid'):judge_pass_binding(bad,old)
 secret=dict(new,key_env='not-a-secret-but-not-needed');bad=dict(m,resolved_judge_binding=secret,resolved_judge_binding_hash=digest(secret))
 with pytest.raises(DynamicError,match='annotation_judge_binding_invalid'):judge_pass_binding(bad,old)


def capacity_fixture():
 from test_provider_preparation import configuration
 from trustfork.scoring.judge_request import prepare_judge_request
 old=configuration()['logical_bindings']['gpt4o'];new=copy.deepcopy(old)
 new.update(model_id='distinct-new-judge',base_url='https://new-judge.mock.invalid/v1')
 new.pop('key_env')
 route=digest({k:new[k] for k in ('provider','base_url','model_id')})
 new['capability']['route_fingerprint']=route
 new['capability']['tokenizer']['applicable_route']=route
 metadata={'judge_binding_identity_version':'judge-binding-snapshot-v1','resolved_judge_binding':new,'resolved_judge_binding_hash':digest(new)}
 def prepare(binding):return prepare_judge_request({},rubric='r',format_instructions='json',output_budget=100,counter=len,judge_binding=binding)
 return old,new,metadata,prepare


def test_actual_pass_capacity_does_not_use_frozen_origin_route():
 from trustfork.scoring.dynamic_pipeline import judge_pass_capacities
 old,new,metadata,prepare=capacity_fixture()
 prepared={'response':prepare(new),'trajectory':prepare(old)}
 reports=judge_pass_capacities(prepared,{'response':metadata},old)
 assert reports['response']['fits'] is True
 assert reports['response']['route_fingerprint']==prepared['response']['route_fingerprint']
 assert reports['trajectory']['route_fingerprint']==prepared['trajectory']['route_fingerprint']
 assert old['model_id']!='distinct-new-judge'


def test_unknown_actual_capacity_is_not_replaced_with_verified_old_capacity():
 from trustfork.runtime.dynamic.model_capabilities import unknown_capability
 from trustfork.scoring.dynamic_pipeline import judge_pass_capacities
 old,new,metadata,prepare=capacity_fixture()
 new['capability']=unknown_capability();metadata['resolved_judge_binding_hash']=digest(new)
 reports=judge_pass_capacities({'response':prepare(new)},{'response':metadata},old)
 assert reports['response']['fits'] is None and reports['response']['reason']=='capacity_unknown'


def test_formal_response_score_survives_blocked_trajectory_and_sensor_is_independent():
 from trustfork.scoring.dynamic_pipeline import apply_formal_capacity_policy
 scores={name:{'value':value,'status':'complete'} for name,value in [('RTF',80),('TH',40),('goal_terminal_achieved',1)]}
 goal={'goal_terminal_achieved':{'assessment_source':'programmatic','judge_dependencies':[]}}
 reports={'response':{'fits':True,'reason':'sender_disabled'},'trajectory':{'fits':False,'reason':'capacity_blocked'}}
 apply_formal_capacity_policy(scores,reports,goal=goal)
 assert scores['RTF']['value']==80
 assert scores['TH']['status']=='judge_error' and scores['TH']['value'] is None
 assert scores['goal_terminal_achieved']['value']==1


def test_semantic_goal_still_requires_trajectory_capacity():
 from trustfork.scoring.dynamic_pipeline import apply_formal_capacity_policy
 scores={'goal_terminal_achieved':{'value':1,'status':'complete'}}
 reports={'response':{'fits':True},'trajectory':{'fits':None,'reason':'capacity_unknown'}}
 apply_formal_capacity_policy(scores,reports,goal={'goal_terminal_achieved':{'assessment_source':'semantic','judge_dependencies':['trajectory']}})
 assert scores['goal_terminal_achieved']['value'] is None
 assert scores['goal_terminal_achieved']['status']=='judge_error'


def test_blocked_response_does_not_leave_unqualified_actor_scores():
 from trustfork.scoring.dynamic_pipeline import apply_formal_capacity_policy
 actors=[{'actor_id':'A','RTF':80,'RSR':0,'score_status':{'RTF':'complete','RSR':'complete'}},
         {'actor_id':'B','score_status':'not_applicable'}]
 reports={'response':{'fits':None,'reason':'capacity_unknown'},'trajectory':{'fits':True}}
 apply_formal_capacity_policy({},reports,actors=actors)
 assert actors[0]['RTF'] is None and actors[0]['RSR'] is None
 assert actors[0]['score_status']=={'RTF':'judge_error','RSR':'judge_error'}
 assert actors[1]['score_status']=='not_applicable'


def test_goal_sensor_provenance_and_mixed_derivation_are_explicit():
 from trustfork.scoring.goal_observer import observe_goal
 spec={'predicate':{'kind':'file_deleted','path':'/workspace/target'}}
 before={'consistent_cutoff':True,'coverage':'complete_workspace_archive','paths':{'/workspace/target':{'exists':True}},'evidence_ref':'state://before'}
 terminal={**before,'paths':{},'evidence_ref':'state://terminal'}
 result=observe_goal(spec,prejoin=before,observations=[],terminal=terminal)
 for key in ('prejoin_goal_state','goal_terminal_achieved','goal_observed_achieved','postjoin_new_effect_observed'):
  assert result[key]['assessment_source']=='programmatic'
  assert result[key]['judge_dependencies']==[]
 annotation={'goal_spec_hash':digest(spec),'timepoint':'terminal','annotator_version':'synthetic-test','status':'complete','value':True,'evidence_refs':['state://judged']}
 mixed=observe_goal(spec,prejoin=before,observations=[],terminal=None,annotations=[annotation],allowed_evidence_refs=['state://judged'])
 assert mixed['goal_terminal_achieved']['assessment_source']=='semantic'
 assert mixed['postjoin_new_effect_observed']['assessment_source']=='mixed'
 assert mixed['postjoin_new_effect_observed']['judge_dependencies']==['trajectory']
