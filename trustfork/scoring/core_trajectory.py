"""Versioned core terminal view over frozen decisions, without streaming drafts.

All non-stream events remain source-bound. Original raw logs are read-only.
This is an assessment representation, not a change to behavior or anchors.
"""
from collections import Counter
import json
from trustfork.runtime.dynamic.common import canonical
from trustfork.runtime.dynamic.common import digest
from trustfork.runtime.dynamic.events import events_digest
from .dynamic_adapter import trajectory_judge_view
from .core_contract import core_bundle, CORE
VERSION = 'core-terminal-decisions-v2'

JSON_KEY='$canonical_json_string'
ESCAPE_KEY='$original_core_object'
def expand_json_strings(value):
    """Expose canonical JSON text structurally so exact subtrees can be pooled.

    Only exact canonical reserialization qualifies. Every byte can be recovered;
    noncanonical text and all natural language remain verbatim. Escape collisions.
    """
    if isinstance(value,str) and len(value)>=160 and value[:1] in ('{','['):
        try:parsed=json.loads(value)
        except (ValueError,RecursionError):return value
        if canonical(parsed).decode()==value:return {JSON_KEY:expand_json_strings(parsed)}
    if isinstance(value,dict):
        if set(value) in ({JSON_KEY},{ESCAPE_KEY}):return {ESCAPE_KEY:[[k,expand_json_strings(v)] for k,v in value.items()]}
        return {k:expand_json_strings(v) for k,v in value.items()}
    if isinstance(value,list):return [expand_json_strings(v) for v in value]
    return value

def restore_json_strings(value):
    if isinstance(value,dict):
        if set(value)=={JSON_KEY}:return canonical(restore_json_strings(value[JSON_KEY])).decode()
        if set(value)=={ESCAPE_KEY}:return {k:restore_json_strings(v) for k,v in value[ESCAPE_KEY]}
        return {k:restore_json_strings(v) for k,v in value.items()}
    if isinstance(value,list):return [restore_json_strings(v) for v in value]
    return value

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
    view=expand_json_strings(view)
    view.update(json_string_representation={'marker':JSON_KEY,'escape':ESCAPE_KEY,'instructions':'A sole '+JSON_KEY+' object is the exact original JSON string, shown structurally for deduplication. Recursively restore children then serialize canonical JSON with sorted keys, UTF-8 and compact separators to recover the exact original string. A sole '+ESCAPE_KEY+' object escapes an original object as key/value pairs. These are input representations, never tool effects or new events.'},
        view=VERSION, subject_scope='whole team terminal safety and task utility',
        evidence_selection={'version':VERSION, 'excluded':{'pi_event.message_update':len(events)-len(selected)},
            'raw_source_events_hash':events_digest(events),
            'unanswered_requests':[e['branch_id']+'::'+e['event_id'] for e in selected if e['event_type']=='model_request_submitted' and not any(r['event_type']=='model_response' and r.get('request_id')==e.get('request_id') for r in selected)],
            'retained_event_types':dict(Counter(e['event_type'] for e in selected)),
            'rule':'Only SDK message_update drafts excluded; complete requests, responses, tool results, delivery, state and all other source events retained for validation. No semantic summaries or content truncation.'})
    # Existing sanitizer proof binds the actual selected validation source.
    view['_sanitizer']['sanitized_view_hash']=digest({k:v for k,v in view.items() if k!='_sanitizer'})
    shell={'scoring_profile':'dynamic-homogeneous-v2','views':{'trajectory':view,
        'response':{'responses':[]}},'response_ids':[], 'prompts':{},'formats':{},
        'sanitizer':view['_sanitizer']}
    return core_bundle(shell),selected
