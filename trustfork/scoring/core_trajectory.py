"""Versioned core terminal view over frozen decisions, without streaming drafts.

All non-stream events remain source-bound. Original raw logs are read-only.
This is an assessment representation, not a change to behavior or anchors.
"""
from collections import Counter
from trustfork.runtime.dynamic.common import digest
from trustfork.runtime.dynamic.events import events_digest
from .dynamic_adapter import trajectory_judge_view
from .core_contract import core_bundle, CORE
VERSION = 'core-terminal-decisions-v1'

def select_core_events(events):
    return [e for e in events if not (e['event_type'] == 'pi_event'
        and e['payload'].get('event', {}).get('type') == 'message_update')]

def trajectory_bundle(events, *, task, private_goals, frozen_state, final_response,
                      observation_complete=True, termination_reason=None):
    selected = select_core_events(events)
    view = trajectory_judge_view(selected, task=task, private_goals=private_goals,
        frozen_state=frozen_state, final_response=final_response,
        scoring_profile='legacy-eight-v1', observation_complete=observation_complete,
        termination_reason=termination_reason)
    view.update(view=VERSION, subject_scope='whole team terminal safety and task utility',
        evidence_selection={'version':VERSION, 'excluded':{'pi_event.message_update':len(events)-len(selected)},
            'raw_source_events_hash':events_digest(events),
            'retained_event_types':dict(Counter(e['event_type'] for e in selected)),
            'rule':'Only SDK message_update drafts excluded; complete requests, responses, tool results, delivery, state and all other source events retained for validation. No semantic summaries or content truncation.'})
    # Existing sanitizer proof binds the actual selected validation source.
    view['_sanitizer']['sanitized_view_hash']=digest({k:v for k,v in view.items() if k!='_sanitizer'})
    shell={'scoring_profile':'dynamic-homogeneous-v2','views':{'trajectory':view,
        'response':{'responses':[]}},'response_ids':[], 'prompts':{},'formats':{},
        'sanitizer':view['_sanitizer']}
    return core_bundle(shell),selected
