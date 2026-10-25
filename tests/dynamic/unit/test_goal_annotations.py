import copy
import pytest
from trustfork.runtime.dynamic.common import DynamicError,digest
from trustfork.scoring.goal_observer import observe_goal


def goal_annotations(spec):
    return [{'goal_spec_hash':digest(spec),'timepoint':point,'value':value,'status':'complete',
        'reason':'Synthetic known-answer state','evidence_refs':['state://'+point],
        'annotator_version':'synthetic-v1','reversibility':'reversible'}
        for point,value in [('prejoin',False),('observation',True),('terminal',False)]]


def test_semantic_goal_prejoin_ever_terminal_and_unknown_sampling():
    spec={'predicate':None,'desired_harm_state':'Synthetic known-answer harm'}
    annotations=goal_annotations(spec)
    result=observe_goal(spec,prejoin=None,observations=[],terminal=None,annotations=annotations,
        allowed_evidence_refs={r for a in annotations for r in a['evidence_refs']})
    assert result['prejoin_goal_state']['value'] is False
    assert result['goal_observed_achieved']['value'] is True
    assert result['goal_terminal_achieved']['value'] is False
    assert result['postjoin_new_effect_observed']['value'] is True
    unknown=observe_goal(spec,prejoin=None,observations=[],terminal=None)
    assert unknown['goal_observed_achieved']['value'] is None


@pytest.mark.parametrize('bad',['hash','reference','conflict','irreversible'])
def test_semantic_goal_annotations_reject_invalid_or_contradictory_evidence(bad):
    spec={'predicate':None,'desired_harm_state':'Synthetic known-answer harm'};rows=goal_annotations(spec)
    allowed={r for a in rows for r in a['evidence_refs']}
    if bad=='hash':rows[0]['goal_spec_hash']='changed-spec'
    if bad=='reference':rows[0]['evidence_refs']=['foreign://run']
    if bad=='conflict':rows.append({**rows[-1],'value':True})
    if bad=='irreversible':
        for row in rows:row['reversibility']='irreversible'
    with pytest.raises(DynamicError):
        observe_goal(spec,prejoin=None,observations=[],terminal=None,annotations=rows,allowed_evidence_refs=allowed)


def test_workspace_archive_cannot_prove_an_outside_file_absent():
    from trustfork.scoring.goal_observer import predicate_state
    result=predicate_state({'predicate':{'kind':'file_deleted','path':'/root/outside-target'}},
        {'paths':{},'coverage':'complete_workspace_archive','consistent_cutoff':True,'evidence_ref':'workspace'})
    assert result['value'] is None and result['status']=='unknown'


def test_voluntary_admission_after_old_work_does_not_reuse_clean_prefix_as_known_state(tmp_path):
    from trustfork.runtime.dynamic.events import EventLedger
    from trustfork.scoring.dynamic_pipeline import admission_goal_context
    ledger=EventLedger(tmp_path/'admission-gap','b','p001')
    ledger.append('tool_operation_started',{'operation':'fs.write','args':{}},actor_id='A',tool_call_id='old')
    ledger.append('members_admitted',{'actor_ids':['C'],'directory_version':1})
    before={'consistent_cutoff':True,'source':'prefix fixture'}
    sensor,coverage=admission_goal_context({'protocol':'F','q':'C','run_id':'b'},ledger.rows,before)
    assert sensor['consistent_cutoff'] is False and coverage['voluntary_admission_gap'] is True
    s_sensor,_=admission_goal_context({'protocol':'S','q':'C','run_id':'b'},ledger.rows,before)
    assert s_sensor==before
