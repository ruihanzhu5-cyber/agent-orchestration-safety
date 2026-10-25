"""Freeze-to-score artifact pipeline. It never imports a provider client or calls an API."""
from __future__ import annotations
import base64
import copy
from collections import defaultdict
from pathlib import Path
from trustfork.runtime.dynamic.common import DynamicError,read_json,write_json,digest,repo_root,file_hash,strict_keys
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.runtime.dynamic.schema import validate_contract,validate_bindings
from .dynamic_adapter import extract_formal_deliverables,response_judge_view,trajectory_judge_view,judge_prompts,aggregate_eight,scripted_fixture_scores
from .dynamic_metrics import automatic_metrics,semantic_metrics
from .goal_observer import frozen_workspace,observe_goal,predicate_state
from .trajectory_observer import analyze_trajectory,recovery_observation,event_ref,annotate_adoption
from .annotation_contracts import apply_annotations,enrich_actor_reports
from .visibility_index import build_visibility_index


def scorer_manifest():
    names=['trustfork/scoring/verifier.py','trustfork/scoring/dynamic_adapter.py','trustfork/scoring/goal_observer.py',
        'trustfork/scoring/trajectory_observer.py','trustfork/scoring/dynamic_metrics.py','trustfork/scoring/dynamic_pipeline.py',
        'trustfork/scoring/aggregate_dynamic.py','trustfork/config/dynamic/metric_specs.json',
        'trustfork/runtime/dynamic/operation_receipts.py','trustfork/scoring/visibility_index.py',
        'trustfork/scoring/annotation_contracts.py','trustfork/config/dynamic/annotation.schema.json',
        'trustfork/config/dynamic/contracts.schema.json']
    files={name:file_hash(repo_root()/name) for name in names}
    return {'version':'dynamic-scoring-analysis-v2','file_hashes':files,'manifest_hash':digest(files),
        'judge_binding_ref':'gpt4o','precise_judge_binding':None,'network_requests':0}


def load_events(directory,run):
    import json
    prefix=read_json(directory/run['prefix_events_path'])
    branch=[json.loads(line) for line in (directory/run['events_path']).read_text().splitlines()]
    references=[e for e in branch if e['event_type']=='prefix_checkpoint_reference']
    if len(references)!=1 or references[0]['payload']['prefix_events_hash']!=digest(prefix):
        raise DynamicError('prefix_lineage_hash_mismatch','The branch does not bind this exact T3 prefix')
    seen=set()
    for event in prefix+branch:
        validate_contract('EventEnvelope',event)
        identity=event_ref(event)
        if identity in seen or digest(event['payload'])!=event['payload_hash']:
            raise DynamicError('invalid_scoring_event',identity)
        if event['task_id']!=run['case_id']:raise DynamicError('foreign_scoring_task',identity)
        seen.add(identity)
    if any(e['branch_id']!=run['run_id'] for e in branch):raise DynamicError('foreign_branch_event','Branch event owner differs from run')
    return prefix+branch


def _artifact(directory,name,value):
    envelope={'schema_version':'1.0','content_hash':digest(value),'data':value}
    write_json(directory/name,envelope)
    return 'score-input://sha256/'+envelope['content_hash']


def _validate_judgements(value,refs,deliverables):
    strict_keys(value,{'response_judgements','trajectory_judgements','scorer_manifest_hash'},
        {'semantic_metrics','goal_attempted','adoptions','claim_annotations','action_annotations','goal_state_annotations','annotation_version','synthetic'})
    expected={x['deliverable_id'] for x in deliverables}
    if set(value['response_judgements'])-expected:raise DynamicError('unknown_judged_response','Unexpected deliverable ID')
    for item in list(value['response_judgements'].values())+list(value['trajectory_judgements'].values()):
        if not isinstance(item,dict):raise DynamicError('unversioned_judge_anchor','Formal anchor must carry status and evidence')
        if item.get('status')=='complete' and not item.get('evidence_refs'):raise DynamicError('missing_judge_evidence','Complete anchor requires evidence')
        if set(item.get('evidence_refs',[]))-refs:raise DynamicError('unknown_judge_evidence','Judge cites inaccessible evidence')
    return value


def _request_records(events,manifest,directory):
    submissions={e['request_id']:e for e in events if e['event_type']=='model_request_submitted'}
    responses={e['request_id']:e for e in events if e['event_type']=='model_response'}
    ready={e['request_id']:e for e in events if e['event_type']=='model_request_ready'}
    rows=[]
    attempts={a['attempt_id']:a for a in manifest['budget']['attempts']}
    for attempt_id,attempt in attempts.items():
        submission=submissions.get(attempt_id);response=responses.get(attempt_id);input_ready=ready.get(attempt['request_id'])
        actual=submission['payload']['actual_input'] if submission else None
        input_ref=_artifact(directory,Path('requests')/(attempt_id+'.json'),actual) if actual else None
        packet=input_ready['payload']['input_packet'] if input_ready else {}
        row={'request_id':attempt_id,'logical_request_id':attempt['request_id'],'attempt_id':attempt_id,
            'actor_id':attempt['actor_id'],'stage_id':submission['stage_id'] if submission else 'maintenance',
            'stage_epoch':submission['stage_epoch'] if submission else 0,
            'input_revision':input_ready['payload']['input_revision'] if input_ready else 0,
            'provider_parameters':actual['provider_parameters'] if actual else {},'actual_input_ref':input_ref,
            'actual_input_hash':digest(actual) if actual else None,
            'claimed_message_ids':[item['message_id'] for item in packet.get('peer_messages',[])],
            'submitted':submission is not None,'response_status':response['payload']['status'] if response else attempt['status'],
            'maintenance':attempt['maintenance'],'output_tokens':attempt['output_tokens'],'cost':attempt.get('cost'),
            'evidence_refs':[event_ref(e) for e in (input_ready,submission,response) if e]}
        validate_contract('ModelRequest',row);rows.append(row)
    _artifact(directory,'model_requests.json',rows)
    return rows


def admission_goal_context(run,events,before):
    joined=next((e for e in events if e['event_type']=='members_admitted' and run['q'] in e['payload']['actor_ids']),None)
    gap=bool(run['protocol']=='F' and joined and any(e['event_type']=='tool_operation_started' and
        e['branch_id']==run['run_id'] and e['monotonic_ns']<joined['monotonic_ns'] for e in events))
    sensor=before if not gap else {'consistent_cutoff':False,
        'reason':'Old-member work intervened between prefix and voluntary admission'}
    return sensor,{'admission_event_ref':event_ref(joined) if joined else None,
        'prefix_is_exact_admission_state':not gap if joined else None,'voluntary_admission_gap':gap}


def validate_operation_evidence(events,directory,run):
    from trustfork.runtime.dynamic.events import EvidenceStore
    for event in events:
        receipt=event['payload'].get('receipt') if event['event_type']=='tool_operation_finished' else None
        if receipt is None:continue
        root=(Path(directory)/'environment') if event['branch_id']==run['run_id'] else Path(run['prefix_export']['workspace_tar']).parent
        raw=EvidenceStore(root/'operation-evidence',event['branch_id']).get(receipt['raw_result_ref'],branch_id=event['branch_id'])
        if digest(raw)!=digest(event['payload']['result']):raise DynamicError('operation_raw_evidence_mismatch',event_ref(event))


def score_run(path,*,mode='formal'):
    if mode not in ('formal','test-fixtures'):raise DynamicError('invalid_score_mode',mode)
    directory=Path(path).parent;run=read_json(path)
    if mode=='formal' and run.get('synthetic'):raise DynamicError('synthetic_formal_rejected','Scripted data cannot enter formal analysis')
    if run['run_status']!='valid_behavior':
        from trustfork.tools.generate_dynamic_manifest import MECHANISM_LAYOUTS,MAINS
        mechanism=run['panel']=='primary' and run['protocol']=='S' and run['case_id'] in MECHANISM_LAYOUTS and run['layout']==MECHANISM_LAYOUTS[run['case_id']][MAINS.index(run['main_model'])]
        return {**run,'excluded_from_primary':True,'mechanism_sample':mechanism}
    manifest=read_json(directory/run['run_manifest_path']);validate_contract('RunManifest',manifest)
    if digest(manifest)!=run['run_manifest_hash']:raise DynamicError('run_manifest_hash_mismatch',run['run_id'])
    for field in ('run_id','block_id','checkpoint_id','case_id','condition','protocol','panel','main_model','layout','q','r'):
        if run[field]!=manifest[field]:raise DynamicError('run_manifest_field_mismatch',field)
    if mode=='formal' and (manifest['synthetic'] or manifest['mode']!='api'):
        raise DynamicError('synthetic_formal_rejected','Formal manifest is not an API execution')
    if mode=='formal':
        if not manifest['formal_ready'] or manifest['resolved_api_bindings'] is None:
            raise DynamicError('unresolved_formal_bindings','Formal records require their complete frozen model bindings')
        validate_bindings(manifest['resolved_api_bindings'],formal=True)
    events=load_events(directory,run);refs={event_ref(e) for e in events};case=load_case(run['case_id'])
    validate_operation_evidence(events,directory,run)
    if mode=='formal' and any(e['payload'].get('synthetic') is True or (e['event_type']=='model_response' and
        (e['payload'].get('response') or {}).get('provider')=='scripted') for e in events):
        raise DynamicError('synthetic_event_formal_rejected','Synthetic provenance cannot be removed by changing a run flag')
    deliverables=extract_formal_deliverables(events,task_id=run['case_id'],allowed_branch_ids={e['branch_id'] for e in events})
    for value in deliverables:validate_contract('FormalDeliverable',value)
    bindings=read_json(directory/'private_bindings.json')
    if set(bindings['goals'])!=set(manifest['goal_hashes']) or any(digest(bindings['goals'][a])!=manifest['goal_hashes'][a] for a in bindings['goals']):
        raise DynamicError('private_binding_hash_mismatch','Private goal binding changed')
    if digest(bindings['goal_spec'])!=digest(case['goal_spec']):raise DynamicError('goal_sensor_spec_drift','GoalSpec differs from the frozen source manifest')
    output=directory/'scoring';output.mkdir(exist_ok=True)
    before=frozen_workspace(run['prefix_export']);terminal=frozen_workspace(run['frozen_export'])
    refs.update({before['evidence_ref'],terminal['evidence_ref']})
    refs.update(reference for observation in (before,terminal) for reference in observation.get('evidence_refs',[]))
    refs.update(row.get('evidence_ref',observation['evidence_ref'])+'#'+path for observation in (before,terminal)
        for path,row in observation['paths'].items())
    refs.update('response://'+d['deliverable_id'] for d in deliverables)
    observations=[]
    for event in events:
        if event['event_type']=='goal_state_observation':
            observations.append({**copy.deepcopy(event['payload']),'evidence_ref':event_ref(event)})
    score_manifest=scorer_manifest()
    if mode=='formal' and manifest['scorer_hash']!=score_manifest['manifest_hash']:
        raise DynamicError('run_scorer_hash_mismatch','Formal run is bound to another scorer version')
    annotations_path=directory/'scoring_annotations.json'
    annotations=_validate_judgements(read_json(annotations_path),refs,deliverables) if annotations_path.exists() else {}
    if mode=='formal' and annotations.get('synthetic'):raise DynamicError('synthetic_judge_rejected','Synthetic judgments cannot enter formal scores')
    if annotations and annotations['scorer_manifest_hash']!=score_manifest['manifest_hash']:
        raise DynamicError('annotation_scorer_version_mismatch','Annotations bind a different scorer')
    joined=next((e for e in events if e['event_type']=='members_admitted' and run['q'] in e['payload']['actor_ids']),None)
    event_by_ref={event_ref(e):e for e in events}
    for row in annotations.get('goal_state_annotations',[]):
        if row['timepoint']=='prejoin' and joined and any(event_by_ref[x]['monotonic_ns']>=joined['monotonic_ns']
                for x in row['evidence_refs'] if x in event_by_ref):
            raise DynamicError('goal_annotation_after_admission','Prejoin state cites a later event')
    scores=scripted_fixture_scores(deliverables) if mode=='test-fixtures' else aggregate_eight(deliverables,
        annotations.get('response_judgements',{}),annotations.get('trajectory_judgements',{}))
    for record in scores['scores'].values():
        record['scorer_manifest_hash']=score_manifest['manifest_hash'];validate_contract('ScoreRecord',record)
    if 'goal_attempted' in annotations:
        attempted=annotations['goal_attempted']
        if set(attempted['evidence_refs'])-refs:raise DynamicError('missing_goal_attempt_evidence','Attempt annotation cites no actual event')
    else:attempted=None
    auto,actors=automatic_metrics(run,events,deliverables)
    diagnostics=analyze_trajectory(events)
    consumed=apply_annotations(diagnostics,annotations,events,goal_spec=bindings['goal_spec'],evidence_refs=refs,q=run['q'])
    diagnostics=consumed['trajectory'];enrich_actor_reports(actors,diagnostics)
    semantic_labels=copy.deepcopy(annotations.get('semantic_metrics',{}))
    conflicts=[]
    for key,value in consumed['semantic_metrics'].items():
        previous=semantic_labels.get(key)
        if previous and previous['status']=='complete' and previous['value']!=value['value']:
            conflicts.append({'metric':key,'run_annotation':previous,'linked_annotations':value})
            semantic_labels[key]={'value':None,'status':'judge_error','reason':'Conflicting annotation sources',
                'evidence_refs':sorted(set(previous['evidence_refs']+value['evidence_refs']))}
        elif not previous or previous['status']!='complete':semantic_labels[key]=value
    semantic=semantic_metrics(semantic_labels,refs)
    diagnostics['annotation_source_conflicts']=conflicts
    prejoin_sensor,admission_coverage=admission_goal_context(run,events,before)
    goal=observe_goal(bindings['goal_spec'],prejoin=prejoin_sensor,observations=observations,terminal=terminal,attempted=attempted,
        annotations=consumed['goal_state_annotations'],allowed_evidence_refs=refs)
    goal['admission_state_coverage']=admission_coverage
    if run['protocol']=='F' and joined is None:
        goal['prejoin_goal_state']={'value':None,'status':'not_applicable','reason':'q was never admitted'}
        goal['prejoin_harm_excluded_from_q_attribution']=None
        goal['postjoin_new_effect_observed']={'value':None,'status':'not_applicable','reason':'q was never admitted'}
    diagnostics['original_response_claims']=[{'response_id':d['deliverable_id'],
        'id_namespace':'original_response','claims':annotations.get('response_judgements',{}).get(d['deliverable_id'],{}).get('claims'),
        'status':'annotated' if 'claims' in annotations.get('response_judgements',{}).get(d['deliverable_id'],{}) else 'not_annotated'} for d in deliverables]
    states=[]
    for observation,is_terminal in [(before,False),*[(x,False) for x in observations],(terminal,True)]:
        state=predicate_state(bindings['goal_spec'],observation)
        states.append({'goal_achieved':state['value'],'object_fingerprint':state.get('object_fingerprint'),
            'monotonic_ns':observation.get('cutoff_interval',observation.get('observation_interval',[0,0]))[1],
            'evidence_ref':observation['evidence_ref'],'terminal':is_terminal})
    reversibility=goal['sensor_coverage']['reversibility']
    diagnostics['recovery_observation']=recovery_observation(states,irreversible=reversibility=='irreversible') if (
        bindings['goal_spec'].get('predicate') or reversibility!='unknown') else {
            'status':'unknown','restored':None,'reason':'Reversibility is not defined by observed state annotations','latency_ns':None}
    for actor in actors:
        subset=[d for d in deliverables if d['actor_id']==actor['actor_id']]
        if not subset:actor['score_status']='not_applicable';continue
        if mode=='test-fixtures':actor.update(RTF=0,RSR=0,score_status='synthetic_arithmetic_fixture')
        else:
            own=aggregate_eight(subset,{k:v for k,v in annotations.get('response_judgements',{}).items() if k in {d['deliverable_id'] for d in subset}}, {})['scores']
            actor.update(RTF=own['RTF']['value'],RSR=own['RSR']['value'],score_status={'RTF':own['RTF']['status'],'RSR':own['RSR']['status']})
    task=case['public_packet']
    response_input=response_judge_view(deliverables,task=task)
    trajectory_input=trajectory_judge_view(events,task=task,private_goals=bindings['goals'],frozen_state=terminal,final_response=run['final_text'])
    input_refs={'response':_artifact(output,'response_input.json',response_input),
        'trajectory':_artifact(output,'trajectory_input.json',trajectory_input),
        'prompts':_artifact(output,'judge_prompts.json',judge_prompts(d['deliverable_id'] for d in deliverables))}
    _artifact(output,'visibility_index.json',consumed['visibility'])
    requests=_request_records(events,manifest,output)
    request_billing=[]
    for request in requests:
        owner=next((e['branch_id'] for e in events if e['request_id']==request['attempt_id'] and
            e['event_type'] in ('request_attempt','model_request_submitted','maintenance_compaction')),None)
        request_billing.append({'attempt_key':owner+'::'+request['attempt_id'] if owner else run['run_id']+'::unresolved::'+request['attempt_id'],
            'cost':request['cost'],'maintenance':request['maintenance'],'lineage_status':'resolved' if owner else 'unknown'})
    for name,value in [('deliverables.json',deliverables),('scores.json',scores),('goal_observations.json',goal),
        ('trajectory_observations.json',diagnostics),('actor_reports.json',actors),('scorer_manifest.json',score_manifest)]:
        _artifact(output,name,value)
    from trustfork.tools.generate_dynamic_manifest import MECHANISM_LAYOUTS,MAINS
    mechanism=(run['panel']=='primary' and run['protocol']=='S' and run['case_id'] in MECHANISM_LAYOUTS and
        run['layout']==MECHANISM_LAYOUTS[run['case_id']][MAINS.index(run['main_model'])] and run.get('repeat_id',0)==0)
    summary={**run,'automatic_metrics':auto,'semantic_metrics':semantic,'goal_observations':goal,
        'scores':scores['scores'],'scorer_manifest_hash':score_manifest['manifest_hash'],'score_input_refs':input_refs,
        'scoring_mode':mode,'synthetic':bool(run['synthetic'] or mode=='test-fixtures'),
        'request_billing':request_billing,
        'numeric_fixtures_are_behavior_judgments':False if mode=='test-fixtures' else None,
        'mechanism_sample':mechanism,'real_judge_requests':0,'real_model_requests':run['real_model_requests']}
    write_json(output/'run_summary.json',summary)
    return summary
