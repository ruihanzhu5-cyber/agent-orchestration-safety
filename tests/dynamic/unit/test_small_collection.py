import pytest
from trustfork.tools.small_api_collection import CollectionRunner,PLAN_VERSION,fixed_matrix

def test_collection_matrix_is_exact_and_does_not_depend_on_judge_gates():
 assert [(x['protocol'],x['condition']) for x in fixed_matrix()]==[('S','HP'),('S','HA'),('F','HP'),('F','HA')]
 assert all(x['case_id']=='p001' and x['team_model']=='deepseekflash' for x in fixed_matrix())
 assert PLAN_VERSION=='small-api-collection-plan-v1'
 assert not hasattr(CollectionRunner,'collect_requires_judge_gate')
