"""Passive opportunities and information provenance, never a risk policy or score."""
from collections import Counter
from trustfork.runtime.dynamic.common import digest,WORK_TOOLS
from .visibility_index import event_ref


def case_information_inventory(case):
    assets=case['deployed_assets']
    source=case['source_task_path']; spec=case['goal_spec']
    return {'case_id':case['case_id'],'source_refs':[source+'/task.toml',case['source_scenario_ref']],
        'public_task_packets':[{'stage_id':s['stage_id'],'content_hash':digest(s['public_task_brief'])} for s in case['public_packet']['stages']],
        'current_packet_policy':'original user_request delivered to each actual task packet recipient',
        'user_request_recipient_constraint':{'status':'unknown','value':None,
            'reason':'Original user_request is reused as public_task_brief; a per-card recipient/use interpretation has not been semantically annotated',
            'evidence_refs':[source+'/task.toml',case['source_scenario_ref']]},
        'shared_workspace':[x for x in assets if x['path'].startswith('workspace/')],
        'original_resources':[x for x in assets if x['path'].endswith(('AGENTS.md','SKILL.md'))],
        'recipient_only_materials':{'status':'unknown','items':[],'reason':'No additional secrecy or access boundary inferred'},
        'goal_sensor':{'deterministic_predicate':spec['predicate'] is not None,
            'semantic_annotations_required':spec['semantic_judge_needed'],'goal_spec_hash':digest(spec),
            'sources':spec['sensor_sources'],'coverage_limits':['Only exported original task paths/services and sampled observations',
                'Absent samples do not prove no transient effect; irreversible exfiltration cannot be undone by workspace cleanup']},
        'additional_acl_created':False,'safety_policy_added':False}


def build_opportunity_report(run,events,visibility,*,private_binding_check=None,profile_metadata=None):
    rows=visibility['records']; checks={}
    for actor in ('Main','A','B','C','D'):
        own=[e for e in events if e['actor_id']==actor]; packets=[r for r in rows if r['observer_actor']==actor and r['source_kind']=='task_packet']
        admissions=[e for e in events if e['event_type']=='members_admitted' and actor in e['payload']['actor_ids']]
        sessions=[e for e in own if e['event_type']=='session_created']; closed=[e for e in own if e['event_type']=='startup_slice_closed']
        outgoing=[e for e in own if e['event_type']=='message_enqueued']
        ids={e['message_id'] for e in outgoing}; exposures=[r for r in rows if r.get('message_id') in ids and r['successful_response']]
        actual=[e for e in own if e['event_type']=='model_request_submitted']
        registries=[e['payload'].get('registry',{}) for e in sessions]
        tools=[]
        for registry in registries:
            names=registry.get('toolNames',registry.get('tool_names',registry.get('tools',[]))) if isinstance(registry,dict) else registry
            if isinstance(names,list):tools.extend(x if isinstance(x,str) else x.get('name') for x in names if isinstance(x,(str,dict)))
        tools=sorted(set(x for x in tools if x))
        checks[actor]={'admitted':{'value':bool(admissions or sessions),'status':'complete',
                'evidence_refs':[event_ref(x) for x in admissions+sessions]},
            'actual_submitted_requests':len(actual),'startup_requests':sum(e['payload'].get('actual_requests',0) for e in closed),
            'startup_terminal_reason':[e['payload']['terminal_status'] for e in closed] or None,
            'startup_evidence_refs':[event_ref(e) for e in closed],
            'task_packet_in_actual_input':{'value':bool(packets),'status':'complete',
                'evidence_refs':sorted({r['actual_request_event_ref'] for r in packets})},
            'work_tools_registered':[x for x in tools if x in WORK_TOOLS],
            'tool_registry_status':'complete' if sessions else 'not_observed',
            'registry_evidence_refs':[event_ref(e) for e in sessions],
            'outgoing_message_count':len(outgoing),'outgoing_evidence_refs':[event_ref(e) for e in outgoing],
            'confirmed_recipient_exposures':len(exposures),
            'exposure_evidence_refs':[r['actual_request_event_ref'] for r in exposures],
            'main_handoff_occurrences':sum(r['observer_actor']==actor and r['source_kind']=='main_handoff' for r in rows)}
    return {'version':'risk-opportunity-v1','run_id':run['run_id'],'protocol':run['protocol'],'actor_checks':checks,
        'profile_exposure_checks':[r for r in rows if r['source_kind'] in ('initial_profile','own_profile_summary','profile_query_result')],
        'profile_metadata':profile_metadata,'private_goal_binding_check':private_binding_check or {'status':'not_checked','evidence_refs':[]},
        'original_resource_exposures':[r for r in rows if r['source_kind']=='original_resource'],
        'channel_availability':[{'channel':k,'actual_input_occurrences':n,'status':'observed',
            'evidence_refs':sorted({r['actual_request_event_ref'] for r in rows if r['source_kind']==k})} for k,n in sorted(Counter(r['source_kind'] for r in rows).items())],
        'measurement_coverage':{'actual_input_index_version':visibility['visibility_version'],
            'main_visible_occurrences':len(visibility['main_visible_records']),'evaluator_full_environment':'separate frozen exports',
            'submitted_and_successful_separate':True,'original_ipi_semantics':'not_annotated'},
        'limitations':['Opportunity is not successful harm or voluntary trust',
            'Shared original task inputs remain accessible without Main handoff; recipient-only meaning requires source evidence',
            'Only exact resource content matches are attributed; partial/truncated reads may remain unknown',
            'No extra warnings, permissions, peer copies, communication mandates or access rules were added']}
