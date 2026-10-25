from trustfork.runtime.dynamic.common import read_json,config_dir,digest
from trustfork.scoring.risk_opportunity import case_information_inventory,build_opportunity_report
from trustfork.scoring.visibility_index import build_visibility_index
from trustfork.runtime.dynamic.events import EventLedger


def test_all_cards_have_evidence_scoped_source_and_goal_sensor_inventory():
    cases=read_json(config_dir()/'cases.json');rows=[case_information_inventory(c) for c in cases.values()]
    assert len(rows)==30 and sum(r['goal_sensor']['deterministic_predicate'] for r in rows)==6
    assert sum(r['goal_sensor']['semantic_annotations_required'] for r in rows)==24
    assert all(r['user_request_recipient_constraint']['status'] in ('unknown','source_bound') for r in rows)
    assert all(r['additional_acl_created'] is False and r['source_refs'] for r in rows)
    assert all(r['current_packet_policy']=='original user_request delivered to each actual task packet recipient' for r in rows)


def test_opportunity_reports_absence_and_actual_exposure_without_risk_score(tmp_path):
    ledger=EventLedger(tmp_path/'events.jsonl','b','p001')
    ledger.append('members_admitted',{'actor_ids':['C']})
    ledger.append('model_request_submitted',{'actual_input':{'messages':[{'role':'user','content':'{"public_task":{"public_task_brief":"task"},"peer_messages":[]}'}],
        'systemPrompt':'public'}},actor_id='C',request_id='r')
    events=ledger.rows;report=build_opportunity_report({'run_id':'b','protocol':'F','q':'C'},events,build_visibility_index(events))
    assert report['actor_checks']['C']['task_packet_in_actual_input']['value'] is True
    assert report['actor_checks']['D']['admitted']['value'] is False
    assert report['actor_checks']['C']['confirmed_recipient_exposures']==0
    assert report['private_goal_binding_check']['status']=='not_checked'
    assert 'risk_score' not in report and 'sufficient_danger' not in report


def test_original_resources_in_system_input_have_separate_sources(tmp_path):
    ledger=EventLedger(tmp_path/'events.jsonl','b','p001');body='Original task resource only, not a private injected goal'
    ledger.append('model_request_submitted',{'actual_input':{'messages':[],'systemPrompt':'Role\n'+body+'\nPublic'}},actor_id='A',request_id='r')
    index=build_visibility_index(ledger.rows,resources=[{'path':'/workspace/AGENTS.md','source_ref':'source://resource','content':body,'content_hash':digest(body)}])
    rows=[x for x in index['records'] if x['source_kind']=='original_resource']
    assert len(rows)==1 and rows[0]['input_occurrence'].startswith('systemPrompt') and rows[0]['observer_actor']=='A'
    assert not index['main_visible_records'] and rows[0]['matching_rule']=='exact_content_span'
