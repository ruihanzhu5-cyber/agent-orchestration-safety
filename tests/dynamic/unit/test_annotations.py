import copy
import pytest
from trustfork.runtime.dynamic.common import DynamicError
from trustfork.scoring.trajectory_observer import analyze_trajectory


def known_annotations(fixture):
    diagnostics=analyze_trajectory(fixture['events']);claim=diagnostics['dynamic_claims'][0];action=diagnostics['action_observations'][0]
    common={'status':'complete','value':True,'reason':'Synthetic known answer','annotator_version':'synthetic-v1'}
    annotations={'annotation_version':'dynamic-annotations-v1',
        'claim_annotations':[{**common,'claim_id':claim['claim_id'],'text_hash':claim['text_hash'],
            'char_span':claim['char_span'],'speaker_actor':'C','stage_epoch':0,'harm_status':'harmful',
            'evidence_refs':[fixture['ref'](fixture['source'])]}],
        'action_annotations':[{**common,'action_id':action['action_id'],'operation_id':'op','actor_id':'A',
            'stage_epoch':0,'harm_status':'harmful','effect_status':'observed',
            'side_effect_evidence_refs':[fixture['ref'](fixture['state'])],
            'evidence_refs':[fixture['ref'](fixture['end']),fixture['ref'](fixture['state'])]}],
        'adoptions':[{**common,'claim_id':claim['claim_id'],'consumer_actor':'A','stage_epoch':0,
            'actual_request_ref':'A-actual','adoption_state':'acted','action_id':action['action_id'],
            'evidence_refs':[fixture['ref'](fixture['submitted']),fixture['ref'](fixture['start']),fixture['ref'](fixture['state'])]}]}
    return diagnostics,annotations


def test_annotations_change_real_observations_actor_reports_and_semantics(known_trajectory):
    from trustfork.scoring.annotation_contracts import apply_annotations,enrich_actor_reports
    diagnostics,annotations=known_annotations(known_trajectory)
    result=apply_annotations(diagnostics,annotations,known_trajectory['events'])
    actors=enrich_actor_reports([{'actor_id':a} for a in ['C','A','Main']],result['trajectory'])
    assert len(actors[0]['harmful_suggestion_events'])==1
    assert len(actors[1]['harmful_action_events'])==1
    assert actors[2]['harmful_suggestion_events']==[]
    assert result['semantic_metrics']['adopted_plan']['value'] is True
    assert result['semantic_metrics']['acted_on_dangerous_advice']['value'] is True
    assert result['trajectory']['adoption_observations'][0]['adoption_state']=='acted'
    assert diagnostics['dynamic_claims'][0]['annotation_status']=='not_annotated'  # source is immutable


@pytest.mark.parametrize('bad',['claim_hash','speaker','epoch','reference','duplicate','no_exposure','no_effect','earlier_effect','proposal_effect'])
def test_annotations_reject_false_links_or_unsubstantiated_actions(known_trajectory,bad):
    from trustfork.scoring.annotation_contracts import apply_annotations
    diagnostics,annotations=known_annotations(known_trajectory)
    if bad=='claim_hash':annotations['claim_annotations'][0]['text_hash']='modified-content'
    if bad=='speaker':annotations['claim_annotations'][0]['speaker_actor']='D'
    if bad=='epoch':annotations['adoptions'][0]['stage_epoch']=1
    if bad=='reference':annotations['action_annotations'][0]['evidence_refs']=['foreign-run::event']
    if bad=='duplicate':annotations['claim_annotations'].append({**annotations['claim_annotations'][0],'value':False,'harm_status':'not_harmful'})
    if bad=='no_exposure':annotations['adoptions'][0]['consumer_actor']='Main'
    if bad=='no_effect':annotations['action_annotations'][0]['effect_status']='unknown'
    if bad=='earlier_effect':annotations['action_annotations'][0]['side_effect_evidence_refs']=[known_trajectory['ref'](known_trajectory['source'])]
    if bad=='proposal_effect':
        from trustfork.runtime.dynamic.common import digest
        events=copy.deepcopy(known_trajectory['events']);state=next(e for e in events if e['event_id']==known_trajectory['state']['event_id'])
        state['event_type']='model_request_submitted';state['payload']={'actual_input':{'messages':[],'systemPrompt':'a proposal, not state'}};state['payload_hash']=digest(state['payload'])
        with pytest.raises(DynamicError,match='side_effect_not_state_evidence'):apply_annotations(diagnostics,annotations,events)
        return
    with pytest.raises(DynamicError):apply_annotations(diagnostics,annotations,known_trajectory['events'])


@pytest.mark.parametrize('state',['quoted','rejected','uncertain'])
def test_quotation_rejection_and_uncertain_consumption_do_not_become_adoption(known_trajectory,state):
    from trustfork.scoring.annotation_contracts import apply_annotations
    diagnostics,annotations=known_annotations(known_trajectory)
    annotations['adoptions'][0]['adoption_state']=state
    annotations['action_annotations']=[]
    result=apply_annotations(diagnostics,annotations,known_trajectory['events'])
    assert 'adopted_plan' not in result['semantic_metrics']
    assert 'acted_on_dangerous_advice' not in result['semantic_metrics']
