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
    ledger.append('model_request_submitted',{'actual_input':{'messages':[]}},actor_id='Main',request_id='main-request')
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
    bad=copy.deepcopy(ledger.rows);bad[1]['payload']['invocation_id']='unrelated'
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


def test_formal_scorer_change_requires_explicit_origin_and_current_lineage():
    from trustfork.scoring.scoring_versions import validate_scorer_lineage
    with pytest.raises(DynamicError,match='run_scorer_hash_mismatch'):validate_scorer_lineage('old','new')
    rescore={'frozen_identity':{'origin_scorer_hash':'old'},'current_scorer_hash':'new'}
    validate_scorer_lineage('old','new',rescore=rescore)
    with pytest.raises(DynamicError,match='rescore_scorer_lineage_mismatch'):
        validate_scorer_lineage('tampered','new',rescore=rescore)


def test_table_three_exports_counterevidence_as_diagnostics():
    import runpy
    from trustfork.runtime.dynamic.common import repo_root
    from trustfork.scoring.aggregate_dynamic import five_tables
    make_row=runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_analysis.py'))['row']
    rows=[make_row('p001','P1',condition,0) for condition in ('HP','HA','MP','MA')]
    rows[0]['semantic_metrics']['counterevidence_opportunity']={'status':'complete','value':True}
    rows[0]['semantic_metrics']['corrected_after_counterevidence']={'status':'complete','value':True}
    tables=five_tables(rows,replicates=10)
    hp=next(r for r in tables['table3'] if r['condition']=='HP')
    assert hp['counterevidence_diagnostics']['applicable_denominator']==1
    assert hp['counterevidence_diagnostics']['correction_given_opportunity']['known_fraction']==1


def test_frozen_identity_checks_additional_service_exports(tmp_path,monkeypatch):
    from trustfork.runtime.dynamic.common import digest,file_hash
    from trustfork.scoring.scoring_versions import frozen_identity
    import trustfork.scoring.dynamic_pipeline as pipeline
    monkeypatch.setattr(pipeline,'load_events',lambda *a:[])
    service=tmp_path/'service.tar';service.write_bytes(b'original synthetic archive bytes')
    manifest={'scorer_hash':'old','resolved_api_bindings':None};write_json(tmp_path/'manifest.json',manifest)
    run={'run_id':'fixture','run_manifest_path':'manifest.json','run_manifest_hash':digest(manifest),
        'prefix_export':{},'frozen_export':{'additional_exports':{'service':{'path':str(service),'sha256':file_hash(service)}}}}
    write_json(tmp_path/'run.json',run)
    before=frozen_identity(tmp_path/'run.json')
    assert before['frozen_archives_hash']!=digest({})
    service.write_bytes(b'changed archive')
    with pytest.raises(DynamicError,match='frozen_archive_hash_mismatch'):frozen_identity(tmp_path/'run.json')


def test_legacy_rescore_needs_original_event_audit_and_reuse_needs_exact_annotation_origin(tmp_path,monkeypatch):
    from trustfork.runtime.dynamic.common import digest,file_hash
    import trustfork.scoring.scoring_versions as versions
    import trustfork.scoring.dynamic_pipeline as pipeline
    run={'run_manifest_hash':'manifest','events_path':'events.jsonl','prefix_events_path':'prefix-events.json'}
    write_json(tmp_path/'run.json',run);(tmp_path/'events.jsonl').write_text('{}\n');write_json(tmp_path/'prefix-events.json',[])
    frozen={'run_manifest_hash':'manifest','origin_scorer_hash':'old'}
    monkeypatch.setattr(versions,'frozen_identity',lambda *a:frozen)
    monkeypatch.setattr(pipeline,'scorer_manifest',lambda:{'manifest_hash':'new','file_hashes':{}})
    def parent(identity):
        identity_hash=digest(identity);directory=tmp_path/'scoring/versions'/identity_hash
        write_json(directory/'run_summary.json',run)
        write_json(directory/'scorer_manifest.json',{'data':{'manifest_hash':'old','file_hashes':{}}})
        files={f.name:file_hash(f) for f in directory.iterdir() if f.name!='version.json'}
        write_json(directory/'version.json',{'identity':identity,'version_id':identity_hash,'files':files})
        write_json(tmp_path/'scoring/current_version.json',{'version_id':identity_hash,'path':'versions/'+identity_hash})
    parent({})
    with pytest.raises(DynamicError,match='rescore_source_seal_unknown'):
        versions.rescore_contract(tmp_path/'run.json',reason='Do not invent legacy seal')
    audit=tmp_path/'original-audit.json'
    write_json(audit,{'source_file_hashes':{str((tmp_path/name).resolve()):file_hash(tmp_path/name) for name in ('events.jsonl','prefix-events.json')}})
    result=versions.rescore_contract(tmp_path/'run.json',reason='Retained original audit',source_audit=audit)
    assert result['legacy_source_audit_hash']==file_hash(audit)
    annotations={'scorer_manifest_hash':'old','response_judgements':{},'trajectory_judgements':{}}
    write_json(tmp_path/'scoring_annotations.json',annotations)
    parent({'frozen_identity':frozen,'annotations_hash':digest(annotations)})
    compatibility={'from_scorer':'old','to_scorer':'new','judge_semantics_unchanged':True}
    assert versions.rescore_contract(tmp_path/'run.json',reason='Compatible aggregation change',annotation_policy='reuse',compatibility=compatibility)['annotation_policy']=='reuse'
    annotations['scorer_manifest_hash']='different-origin';write_json(tmp_path/'scoring_annotations.json',annotations)
    with pytest.raises(DynamicError,match='annotation_reuse_origin_mismatch'):
        versions.rescore_contract(tmp_path/'run.json',reason='Cannot reuse unrelated annotations',annotation_policy='reuse',compatibility=compatibility)
