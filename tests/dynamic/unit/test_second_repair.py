import copy
import json
import pytest
from trustfork.runtime.dynamic.common import DynamicError,read_json,write_json
from trustfork.runtime.dynamic.events import EventLedger
from trustfork.runtime.dynamic.membership import Membership
from trustfork.runtime.dynamic.lifecycle import Lifecycle
from trustfork.runtime.dynamic.scheduler import Scheduler
from trustfork.runtime.dynamic.delegations import Delegations
from trustfork.scoring.visibility_index import build_visibility_index
from trustfork.scoring.aggregate_dynamic import counterevidence_summary


@pytest.mark.parametrize('actor',['C','D'])
@pytest.mark.parametrize('status',['queued','started','terminal'])
def test_startup_protection_ends_with_the_matching_slice(tmp_path,actor,status):
    ledger=EventLedger(tmp_path/'events','branch','p001');members=Membership(ledger)
    members.admit_atomic(['C','D']);life=Lifecycle(ledger)
    scheduler=Scheduler('block',ledger,members,life);work=Delegations(ledger,members)
    work.startup_protected=scheduler.protects_delegation
    scheduler.begin_startup(['C','D'])
    row=work.prepare(actor,'original',source='runtime_startup',stage_id=life.stage_id)
    scheduler.bind_startup(row)
    for action in [lambda:work.update(row['delegation_id'],'next'),lambda:work.cancel(row['delegation_id'])]:
        with pytest.raises(DynamicError,match='startup_contract_active'):action()
    scheduler._close_startup(actor,'four_request_limit')
    work.get(row['delegation_id'])['status']=status
    if status=='queued':
        assert work.update(row['delegation_id'],'next')['task_text']=='next'
        work.cancel(row['delegation_id'])
    else:
        with pytest.raises(DynamicError,match='delegation_not_editable'):work.update(row['delegation_id'],'next')
        with pytest.raises(DynamicError,match='delegation_not_cancellable'):work.cancel(row['delegation_id'])
    other='D' if actor=='C' else 'C'
    assert scheduler.startup[other]['status']=='open'
    # JSON checkpoint state retains the same scoped contract.
    scheduler.startup=json.loads(json.dumps(scheduler.startup))
    assert not scheduler.protects_delegation(row)


def test_startup_wrong_invocation_and_epoch_are_not_protected(tmp_path):
    ledger=EventLedger(tmp_path/'events','b','p001');members=Membership(ledger);members.admit_atomic(['C','D'])
    life=Lifecycle(ledger);scheduler=Scheduler('b',ledger,members,life);scheduler.begin_startup(['C'])
    row={'actor_id':'C','source':'runtime_startup','stage_epoch':0,'stage_id':life.stage_id,'invocation_id':'original'}
    scheduler.bind_startup(row)
    assert scheduler.protects_delegation(row)
    assert not scheduler.protects_delegation({**row,'invocation_id':'other'})
    life.epoch=1
    assert not scheduler.protects_delegation(row)


@pytest.mark.parametrize('source,kind',[('runtime_startup','runtime_startup_assignment'),('main_voluntary','main_handoff'),('initial_plan','initial_assignment')])
def test_assignment_attribution_requires_actual_consumption_and_lineage(tmp_path,source,kind):
    ledger=EventLedger(tmp_path/'events','b','p001')
    prepared=ledger.append('delegation_prepared',{'actor_id':'C','source':source,'invocation_id':'i','delegation_id':'d'},actor_id='Main',request_id='main-request')
    assert build_visibility_index(ledger.rows)['records']==[]
    packet={'work_assignment':{'source':source,'invocation_id':'i','task_text':'same content'}}
    for identity in ['failed','successful']:
        ledger.append('model_request_submitted',{'actual_input':{'messages':[{'role':'user','content':json.dumps(packet)}]}},actor_id='C',request_id=identity)
    ledger.append('model_response',{'status':'success'},actor_id='C',request_id='successful')
    rows=build_visibility_index(ledger.rows)['records']
    assert len(rows)==2 and all(r['source_kind']==kind for r in rows)
    assert [r['successful_response'] for r in rows]==[False,True]
    assert all(r['source_event_ref'].endswith('::'+prepared['event_id']) for r in rows)
    bad=copy.deepcopy(ledger.rows);bad[0]['payload']['invocation_id']='unrelated'
    assert all(r['source_kind']=='unknown_assignment' for r in build_visibility_index(bad)['records'])


def test_counterevidence_denominators_exclude_unknown_and_no_opportunity():
    def row(opportunity,corrected):
        def value(v):return {'value':v,'status':'not_annotated' if v is None else 'complete'}
        return {'semantic_metrics':{'counterevidence_opportunity':value(opportunity),'corrected_after_counterevidence':value(corrected)}}
    result=counterevidence_summary([row(True,True),row(True,False),row(True,None),row(False,False),row(None,None)],planned=7)
    assert result['applicable_denominator']==3
    assert result['judged_denominator']==2
    assert result['missing_correction_count']==1 and result['opportunity_unknown_count']==1
    assert result['correction_given_opportunity']['known_fraction']==.5


def test_failed_score_build_keeps_previous_current_and_archive(tmp_path,monkeypatch):
    import trustfork.scoring.scoring_versions as versions
    path=tmp_path/'run.json';write_json(path,{})
    output=tmp_path/'scoring';write_json(output/'current_version.json',{'version_id':'old','path':'versions/old'})
    write_json(output/'versions/old/scores.json',{'old':True})
    monkeypatch.setattr(versions,'frozen_identity',lambda p:{'fixed':True})
    def fail(*args,output_override,**kwargs):
        write_json(output_override/'scores.json',{'partial':True})
        raise DynamicError('judge_failed','mock failure')
    with pytest.raises(DynamicError,match='judge_failed'):
        versions.publish_score(path,mode='formal',rescore=None,score=fail)
    assert read_json(output/'current_version.json')['version_id']=='old'
    assert read_json(output/'versions/old/scores.json')=={'old':True}
    assert not list(tmp_path.glob('.scoring-pending-*'))
