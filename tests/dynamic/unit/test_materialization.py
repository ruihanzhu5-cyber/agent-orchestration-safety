import copy
import pytest
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.runtime.dynamic.common import DynamicError,write_json
from trustfork.tools.materialize_dynamic import preserve_readiness,verify_frozen_mapping


def test_materialization_preserves_source_bound_runtime_evidence_without_promoting_untested_cards():
    case=load_case('p001');previous={'p001':{'deployed_asset_hash':case['deployed_asset_hash'],
        'restore_executed':'pass_quiescent_filesystem_only','test_evidence':['synthetic://prior-evidence'],
        'goal_observer':'runtime_verified'}}
    old=copy.deepcopy(previous)
    merged=preserve_readiness({'p001':case},previous)
    assert merged['p001']['restore_executed']=='pass_quiescent_filesystem_only'
    assert merged['p001']['test_evidence']==['synthetic://prior-evidence'] and previous==old
    fresh=preserve_readiness({'p001':case},{})
    assert fresh['p001']['restore_executed']=='not_tested' and fresh['p001']['goal_observer']=='not_tested'
    previous['p001']['deployed_asset_hash']='modified-source'
    with pytest.raises(DynamicError,match='readiness_source_drift'):preserve_readiness({'p001':case},previous)


def test_materialization_refuses_frozen_catalog_drift(tmp_path):
    path=tmp_path/'catalog.json';write_json(path,{'original':'value'})
    verify_frozen_mapping(path,{'original':'value'})
    with pytest.raises(DynamicError,match='frozen_mapping_drift'):verify_frozen_mapping(path,{'original':'changed'})
