"""Prepare the complete immutable Judge payload and independently preflight it.

This module has no sender and never imports provider SDKs. Local BPE counts of a
canonical wire payload are diagnostics, not verified provider chat framing.
"""
import hashlib
import importlib.metadata
import os
from pathlib import Path
from functools import lru_cache
from trustfork.runtime.dynamic.common import DynamicError,canonical,digest
from trustfork.runtime.dynamic.model_capabilities import validate_capability
from .trajectory_codec import INSTRUCTIONS,VERSION


@lru_cache(maxsize=1)
def offline_counter():
    # Resolve only a pre-existing cache. A miss must not invoke tiktoken's HTTP loader.
    cache=Path(os.environ.get('TIKTOKEN_CACHE_DIR',''))
    url='https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken'
    p=cache/hashlib.sha1(url.encode()).hexdigest()
    if not p.is_file():raise DynamicError('offline_tokenizer_unavailable','Existing o200k cache required; network disabled')
    # tiktoken verifies its own pinned cache hash; prevent every fallback read_file.
    import tiktoken,tiktoken.load
    old=tiktoken.load.read_file
    def forbidden(*a,**k):raise DynamicError('offline_tokenizer_unavailable','Cache invalid; downloads forbidden')
    try:
        tiktoken.load.read_file=forbidden
        enc=tiktoken.get_encoding('o200k_base')
    finally:tiktoken.load.read_file=old
    return lambda text:len(enc.encode(text,disallowed_special=()))


def prepare_judge_request(view,*,rubric,format_instructions,output_budget=None,tools=None,parameters=None,
                          counter=None,representation='legacy-full',output_token_parameter='max_tokens'):
    if output_budget is not None and (type(output_budget) is not int or output_budget<=0):
        raise DynamicError('invalid_judge_output_budget','Judge output reserve must be explicit positive integer or unknown')
    params=dict(parameters or {})
    if output_token_parameter in params:raise DynamicError('duplicate_output_budget','Reserve supplied twice')
    if output_budget is not None:params[output_token_parameter]=output_budget
    system=rubric+'\n\n'+format_instructions
    if representation==VERSION:system+='\n\n'+INSTRUCTIONS
    request={'messages':[{'role':'system','content':system},{'role':'user','content':canonical(view).decode()}],
        'tools':tools or [],'parameters':params}
    counter_info={'id':'supplied-test-counter','version':'fixture','count_method':'fixture-exact'}
    if counter is None:
        try:
            counter=offline_counter()
            counter_info={'id':'o200k_base','version':importlib.metadata.version('tiktoken'),
                'count_method':'local-canonical-payload-bpe-estimate'}
        except DynamicError:counter_info={'id':None,'version':None,'count_method':'unavailable'}
    n=counter(canonical(request).decode()) if counter else None
    return {'version':'prepared-judge-request-v1','request':request,'request_hash':digest(request),
        'representation':representation,'representation_hash':digest(view),'input_tokens':n,
        'tokenizer':counter_info,'output_budget':output_budget,'output_token_parameter':output_token_parameter,
        'output_budget_scope':'Judge only; independent of agent 4096 and team 48000',
        'provider_framing_verified':False,'cognitive_equivalence':'not_tested_offline' if representation==VERSION else 'legacy'}


def capacity_report(prepared,capability):
    c=validate_capability(capability);n=prepared['input_tokens'];output=prepared['output_budget'];framing=c['framing_tokens']
    unknown=(c['status']!='verified' or n is None or output is None or framing is None or
        c['effective_context_tokens'] is None or c['max_output_tokens'] is None or c['tokenizer'] is None or
        c['output_token_parameter']!=prepared['output_token_parameter'])
    if c['tokenizer'] and prepared['tokenizer']['count_method']!=c['tokenizer']['count_method']:unknown=True
    if c['tokenizer'] and prepared['tokenizer']['id']!=c['tokenizer']['id']:
        # Synthetic counters are explicitly declared by unit fixtures only.
        if not (prepared['tokenizer']['count_method']=='fixture-exact' and c['tokenizer']['count_method']=='fixture-exact'):unknown=True
    overflow=bool(n is not None and output is not None and c['effective_context_tokens'] is not None and
        n+output+(framing or 0)>c['effective_context_tokens']) or bool(output is not None and c['max_output_tokens'] is not None and output>c['max_output_tokens'])
    fits=None if unknown else not overflow
    return {'version':'capacity-report-v1','request_hash':prepared['request_hash'],'capacity_status':c['status'],
        'capability_hash':digest(c),'input_tokens':n,'output_reserved':output,'framing_tokens':framing,
        'effective_context_tokens':c['effective_context_tokens'],'fits':fits,'can_send':False,'sender_enabled':False,
        'reason':'capacity_blocked' if overflow else 'capacity_unknown' if unknown else 'sender_disabled',
        'score_status':'judge_error','behavior_run_status':'unchanged','independent_judge_budget':True}
