import copy
import pytest
from trustfork.agents.pi_dynamic import PiDynamic
from trustfork.runtime.dynamic.events import EventLedger
from trustfork.runtime.dynamic.membership import Membership
from trustfork.runtime.dynamic.common import DynamicError


def bound(tmp_path,condition='HP'):
    p=PiDynamic('p001',tmp_path,layout='P2',legacy=True);p.ledger=EventLedger(tmp_path/'events.jsonl','b','p001');p.membership=Membership(p.ledger)
    p.history={'synthetic':True,'actor_states':{a:[{'task_id':'p002','synthetic':True,'status':'synthetic_fixture_only'},
        {'task_id':'p007','synthetic':True,'status':'failed'}] for a in ('Main','A','B')}}
    p._bind_profiles(condition);return p


def test_old_members_have_empty_external_profiles_and_history_counts_are_not_successes(tmp_path):
    p=bound(tmp_path);s=p.profile_service
    for a in 'AB':
        assert s.get_public_profile(a,'full')['direct_team_tasks']==2
        assert s.get_public_profile(a,'full')['external_record']['evaluated_tasks']==0
        assert s.get_public_profile(a,'full')['external_record']['completion_rate_pct'] is None
        assert s.get_profile_statistics(a,'recent')['evaluated_tasks']==0
        assert s.get_profile_statistics(a,'family')[0]['evaluated_tasks']==0
        for method,ref in [(s.get_profile_record,f'profile://{a}/records/01'),(s.get_work_sample,f'profile://{a}/work-samples/01')]:
            with pytest.raises(DynamicError) as err:method(ref)
            assert err.value.code!='profile_not_found'
        with pytest.raises(DynamicError) as err:s.get_historical_config(f'history_config_{a}_v1')
        assert err.value.code!='profile_not_found'
        assert s.bundles[a]['history_provenance']['successful_tasks'] is None


def test_profiles_do_not_leak_current_goal_and_actual_model_labels_follow_layout(tmp_path):
    p=bound(tmp_path/'normal');normal=copy.deepcopy(p.profile_service.bundles)
    p._bind_profiles('HA');assert p.profile_service.bundles==normal
    assert p.profile_service.get_public_profile('C')['actual_model_label'] is None
    p.resolved_api_bindings={'logical_bindings':{'gpt4o':{'model_id':'exact-model-a'},'deepseekflash':{'model_id':'exact-model-b'}}}
    p._bind_profiles('HP')
    assert p.profile_service.get_public_profile('C')['actual_model_label']=='exact-model-b'
    assert p.profile_service.get_public_profile('D')['actual_model_label']=='exact-model-a'
    assert p.profile_metadata['renderer_version'] and p.profile_metadata['profile_corpus_hash']
