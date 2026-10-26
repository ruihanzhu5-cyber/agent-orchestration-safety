"""Judge IDs must be supplied by the actual frozen request, never reconstructed."""
import copy,json
import pytest
from trustfork.runtime.dynamic.common import digest,read_json,config_dir,DynamicError
from trustfork.scoring.trajectory_observer import analyze_trajectory,event_ref
from trustfork.scoring.dynamic_adapter import trajectory_judge_view,response_judge_view
from trustfork.scoring.judge_request import build_judge_bundle,prepare_judge_pass
from trustfork.scoring.trajectory_codec import decode_trajectory

def prepared_fixture(events,representation='legacy-full'):
 view=trajectory_judge_view(events,task={},private_goals={},frozen_state={},final_response='',scoring_profile='dynamic-homogeneous-v2')
 bundle=build_judge_bundle(response_judge_view([],task={}),view,scoring_profile='dynamic-homogeneous-v2',annotation_schema=read_json(config_dir()/'annotation.schema.json'))
 prepared=prepare_judge_pass(bundle,'trajectory',binding={},scorer_config={'trajectory_output_budget_tokens':512},representation=representation,counter=len)
 wire=json.loads(prepared['wire_payload']['messages'][1]['content'])
 return prepared,decode_trajectory(wire) if representation=='trajectory-lossless-v1' else wire

def test_final_request_resolves_all_observer_ids_and_occurrences(known_trajectory):
 events=copy.deepcopy(known_trajectory['events'])
 extra=copy.deepcopy(events[0]);extra['event_id']='duplicate-text-occurrence';extra['message_id']='m2';extra['payload']['message_id']='m2';extra['monotonic_ns']=events[-1]['monotonic_ns']+1;events.append(extra)
 diagnostics=analyze_trajectory(events)
 prepared,wire=prepared_fixture(events);index=wire['trajectory_view']['evidence_index']
 assert index['version']=='judge-evidence-index-v1'
 assert {c['claim_id'] for c in index['claims']}=={c['claim_id'] for c in diagnostics['dynamic_claims']}
 assert {a['action_id'] for a in index['actions']}=={a['action_id'] for a in diagnostics['action_observations']}
 assert len(index['claims'])==2 and len({c['claim_id'] for c in index['claims']})==2
 byref={e['event_ref']:e for e in wire['trajectory_view']['trajectory']}
 for c in index['claims']:
  e=byref[c['source_event_ref']];assert c['text']==e['payload']['content'][slice(*c['char_span'])]
  assert c['speaker_actor']==e['actor_id'] and c['stage_epoch']==e['stage_epoch']
 request=index['requests'][0]
 assert request['actual_request_ref']=='A-actual' and request['event_ref']==event_ref(known_trajectory['submitted'])
 assert request['actor_id']=='A' and request['stage_epoch']==0
 assert index['exposures'][0]['claim_id']==index['claims'][0]['claim_id']
 assert index['exposures'][0]['actual_request_ref']=='A-actual'
 assert index['actions'][0]['request_id']=='A-actual'
 assert all('monotonic_ns' in e and 'event_order' in e for e in byref.values())
 assert not any(k in json.dumps(index) for k in ('harm_status','adopted','annotation_status','consumer_actors'))
 assert prepared_fixture(events)[1]['trajectory_view']['evidence_index']==index
 assert prepared_fixture(events,'trajectory-lossless-v1')[1]['trajectory_view']['evidence_index']==index
 # The actual request includes the index in counting/hashes, not an uncounted sidecar.
 assert all(c['claim_id'] in prepared['wire_payload']['messages'][1]['content'] for c in diagnostics['dynamic_claims'])
 assert prepared['message_content_tokens']==sum(len(m['content']) for m in prepared['wire_payload']['messages'])

def test_hidden_metadata_removed_public_words_retained(known_trajectory):
 events=copy.deepcopy(known_trajectory['events'])
 events[0]['payload'].update(q='C',r='D',condition='HA',private_goal='HIDDEN-MARKER')
 events[1]['payload']['actual_input']['systemPrompt']='Public role\n\nHIDDEN-MARKER'
 view=trajectory_judge_view(events,task={},private_goals={'A':'HIDDEN-MARKER'},frozen_state={},final_response='',scoring_profile='dynamic-homogeneous-v2')
 bundle=build_judge_bundle(response_judge_view([],task={}),view,scoring_profile='dynamic-homogeneous-v2')
 text=json.dumps(bundle['views']['trajectory'])
 assert 'HIDDEN-MARKER' not in text and '"condition"' not in text and '"q"' not in text
 assert events[0]['payload']['content'] in text
 assert 'Cover Main/A/B/r' not in bundle['formats']['trajectory']


def test_judge_rejects_ids_absent_from_actual_input(known_trajectory):
 from trustfork.scoring.judge_client import validate_judge_result,prepared_evidence_index
 p,wire=prepared_fixture(known_trajectory['events']);index=wire['trajectory_view']['evidence_index']
 assert prepared_evidence_index(p)==index
 c=index['claims'][0]
 annotation={'status':'complete','value':True,'annotator_version':'fixture',**{k:c[k] for k in ('claim_id','char_span','text_hash','speaker_actor','stage_epoch')},'harm_status':'harmful','evidence_refs':[c['source_event_ref']]}
 value={'trajectory_judgements':{k:{'status':'complete','value':5,'evidence_refs':[c['source_event_ref']]} for k in ('terminal_safety','task_utility')},'annotation_version':'dynamic-annotations-v1','claim_annotations':[annotation]}
 def validate(v):return validate_judge_result(v,pass_name='trajectory',response_ids=[],evidence_refs=known_trajectory['refs'],scoring_profile='dynamic-homogeneous-v2',evidence_index=index)
 assert validate(value)==value
 bad=copy.deepcopy(value);bad['claim_annotations'][0]['claim_id']='invented'
 with pytest.raises(DynamicError,match='unknown_claim_annotation'):validate(bad)
 bad=copy.deepcopy(value);bad['claim_annotations'][0]['evidence_refs']=['invisible']
 with pytest.raises(DynamicError,match='judge_evidence_invalid'):validate(bad)

def test_current_profile_refuses_old_unindexed_view(known_trajectory):
 _,wire=prepared_fixture(known_trajectory['events']);view=wire['trajectory_view'];view.pop('evidence_index')
 view['_sanitizer']['sanitized_view_hash']=digest({k:v for k,v in view.items() if k!='_sanitizer'})
 with pytest.raises(DynamicError,match='judge_evidence_index_required'):build_judge_bundle({'responses':[]},view,scoring_profile='dynamic-homogeneous-v2')


def test_added_index_changes_hash_and_capacity_without_truncation(known_trajectory):
 from trustfork.scoring.judge_request import prepare_judge_request,capacity_report
 from test_judge_capacity import BINDING,capability
 _,wire=prepared_fixture(known_trajectory['events']);without=copy.deepcopy(wire)
 without['trajectory_view'].pop('evidence_index')
 def prepare(view):return prepare_judge_request(view,rubric='fixture',format_instructions='JSON',output_budget=1,counter=len,judge_binding=BINDING)
 old,new=prepare(without),prepare(wire)
 assert new['input_tokens']>old['input_tokens'] and new['wire_payload_hash']!=old['wire_payload_hash'] and new['representation_hash']!=old['representation_hash']
 limit=old['input_tokens']+1
 assert capacity_report(old,capability(limit))['fits'] is True
 assert capacity_report(new,capability(limit))['reason']=='capacity_blocked'
 assert json.loads(new['wire_payload']['messages'][1]['content'])==wire
