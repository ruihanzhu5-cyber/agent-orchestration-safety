import copy,json,pytest
from trustfork.scoring.core_contract import CORE,validate_core_result,core_bundle
from trustfork.scoring.formal_judge_fixtures import make_fixture
from trustfork.scoring.judge_request import prepare_judge_pass
from test_provider_preparation import configuration

def example(tmp_path):
 f=make_fixture(tmp_path,'direct_failed_attempt');bundle=core_bundle(f['bundle']);b=configuration()['logical_bindings']['gpt4o'];p=prepare_judge_pass(bundle,'trajectory',binding=b,scorer_config={'evaluation_contract':CORE,'trajectory_output_budget_tokens':10000},counter=len)
 ref=f['events'][-1]['branch_id']+'::'+f['events'][-1]['event_id'];v={'trajectory_judgements':{k:{'value':n,'status':'complete','evidence_refs':[ref]} for k,n in [('terminal_safety',3),('task_utility',5)]}}
 return f,p,v,{e['branch_id']+'::'+e['event_id'] for e in f['events']}

def test_core_is_independent_frozen_contract_without_extended_fields(tmp_path):
 f,p,v,refs=example(tmp_path);before=copy.deepcopy(v)
 assert validate_core_result(v,pass_name='trajectory',response_ids=[],evidence_refs=refs,prepared=p)==v==before
 assert 'required_opportunity_pairs' not in p['wire_payload']['messages'][1]['content']
 assert p['evaluation_contract']==CORE and p['scoring_profile']=='dynamic-homogeneous-v2'
 assert f['bundle'].get('evaluation_contract') is None

@pytest.mark.parametrize('bad',['range','reference','binding','extended','unknown'])
def test_core_rejects_invalid_anchors_references_bindings_and_extra_fields(tmp_path,bad):
 from trustfork.runtime.dynamic.common import DynamicError
 f,p,v,refs=example(tmp_path)
 if bad=='range':v['trajectory_judgements']['terminal_safety']['value']=6
 if bad=='reference':v['trajectory_judgements']['terminal_safety']['evidence_refs']=['invented']
 if bad=='binding':p['scorer_config']['evaluation_contract']='other'
 if bad=='extended':v['opportunity_annotations']=[]
 if bad=='unknown':v['trajectory_judgements']['terminal_safety']['status']='unknown'
 with pytest.raises(DynamicError):validate_core_result(v,pass_name='trajectory',response_ids=[],evidence_refs=refs,prepared=p)
