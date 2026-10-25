"""Explicit host HTTP boundary. Task tools retain the bridge's deny-all network guard."""
from __future__ import annotations
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from .common import DynamicError,digest,canonical
from .artifacts import append_jsonl


def resolve_provider(config,alias):
    if alias not in ('gpt4o','deepseekflash'):raise DynamicError('unknown_model_alias',alias)
    binding=config.get('logical_bindings',{}).get(alias,{})
    required=('provider','base_url','model_id','key_env','context_window','max_output_tokens','supported_parameters',
        'api','compat','output_token_parameter')
    missing=[alias+'.'+k for k in required if binding.get(k) is None]
    if missing:raise DynamicError('unresolved_provider_binding','No model inference or fallback',evidence=missing)
    if binding['api']!='openai-completions':raise DynamicError('unsupported_provider_api',binding['api'])
    if binding['output_token_parameter'] not in ('max_tokens','max_completion_tokens'):
        raise DynamicError('unsupported_output_parameter',binding['output_token_parameter'])
    if 'temperature' not in binding['supported_parameters'] or binding['output_token_parameter'] not in binding['supported_parameters']:
        raise DynamicError('unsupported_planned_parameter','temperature=0.2 and output parameter require route support')
    return binding.copy()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def real_http(url,body,key,timeout):
    request=urllib.request.Request(url,data=body.encode(),method='POST',headers={
        'Content-Type':'application/json','Authorization':'Bearer '+key})
    opener=urllib.request.build_opener(_NoRedirect())
    try:response=opener.open(request,timeout=timeout)
    except urllib.error.HTTPError as error:response=error
    headers={k.lower():v for k,v in response.headers.items() if k.lower() in
        ('content-type','x-request-id','request-id','retry-after')}
    chunks=[];read_error=False
    try:
        while chunk:=response.read(65536):chunks.append(chunk)
    except (OSError,TimeoutError):read_error=True
    finally:response.close()
    return {'status':response.code,'headers':headers,'body':b''.join(chunks).decode('utf-8',errors='replace'),'read_error':read_error}


class ProviderTransport:
    """One request per ledger attempt. No implicit retry/model substitution."""
    def __init__(self,config,*,mode,journal,authorize_real=False,http=None,max_requests=None,kind='model',experiment=None):
        if mode not in ('mock','api'):raise DynamicError('invalid_provider_mode',mode)
        if mode=='mock' and http is None:raise DynamicError('mock_transport_required','Mock must be injected, never external')
        if mode=='api' and (http is not None or not authorize_real or config.get('mode')!='api' or config.get('real_api_enabled') is not True):
            raise DynamicError('real_api_disabled','Explicit API mode, local flag and run authorization are all required')
        if type(max_requests) is not int or max_requests<1:raise DynamicError('request_budget_required','Explicit request ceiling required')
        self.active_aliases={config['judge_binding']} if kind=='judge' else set(experiment.model_refs.values()) if experiment is not None else set(config['logical_bindings'])
        self.config,self.mode,self.journal=config,mode,Path(journal)
        if self.journal.exists():raise DynamicError('provider_journal_exists','Select a new attempt; no implicit budget reset over existing requests')
        self.transport_id=uuid.uuid4().hex
        self.http=http if mode=='mock' else real_http
        self.kind=kind;self.limit=max_requests;self.count=0;self.lock=threading.Lock()
        self.synthetic=mode=='mock';self.source='mock' if self.synthetic else 'api'
        self.reserved_cost=0;self.window=[];self.results={}
        if mode=='api':
            from .schema import validate_bindings
            validate_bindings(config,formal=True,required_aliases=self.active_aliases)
            limits=(config.get('execution_limits') or {}).get(kind)
            required=('max_cost_usd','requests_per_minute','tokens_per_minute','prices_per_million')
            if not isinstance(limits,dict) or any(limits.get(k) is None for k in required):
                raise DynamicError('execution_limits_unknown','Independent request/cost/RPM/TPM and route prices required')
            self.limits=limits

    def _reserve_api(self,binding,body):
        from .model_capabilities import binding_capability
        from .token_accounting import count_request,route_counting_policy
        capability=binding_capability(binding)
        accounting=count_request(body,route_counting_policy(binding))
        if capability['status']!='verified' or accounting['estimated_total_input_tokens'] is None:
            raise DynamicError('provider_capacity_unknown','Verified route framing and tokenizer required')
        n=accounting['estimated_total_input_tokens'];out=body.get(binding['output_token_parameter'])
        if type(out) is not int or out<=0 or out>capability['max_output_tokens'] or n+out>capability['effective_context_tokens']:
            raise DynamicError('provider_capacity_blocked','Complete input/output cannot fit; no fallback')
        price=self.limits['prices_per_million'].get(binding['model_id'])
        if not isinstance(price,dict) or any(type(price.get(k)) not in (int,float) or price[k]<0 for k in ('input','output')):
            raise DynamicError('provider_price_unknown','Exact route/model input/output prices required')
        worst=(n*price['input']+out*price['output'])/1e6
        now=time.monotonic();self.window=[x for x in self.window if now-x[0]<60]
        if self.reserved_cost+worst>self.limits['max_cost_usd']:
            raise DynamicError('provider_cost_budget_exhausted','Worst-case reservations exceed configured cost ceiling')
        if len(self.window)>=self.limits['requests_per_minute'] or sum(x[1] for x in self.window)+n+out>self.limits['tokens_per_minute']:
            raise DynamicError('provider_rate_budget_blocked','Do not silently retry; resume after rate window with the same evidence')
        self.reserved_cost+=worst;self.window.append((now,n+out))

    def request(self,alias,wire,*,request_id,timeout=60):
        if alias not in self.active_aliases:raise DynamicError('inactive_provider_alias','Alias is outside frozen role scope')
        binding=resolve_provider(self.config,alias)
        expected=binding['base_url'].rstrip('/')+'/chat/completions'
        if wire.get('url')!=expected or wire.get('method')!='POST':
            raise DynamicError('provider_route_mismatch','Request must use the exact configured route; redirects forbidden')
        body=json.loads(wire['body'])
        if body.get('model')!=binding['model_id']:raise DynamicError('provider_model_mismatch','No fallback model is allowed')
        from .token_accounting import count_request,route_counting_policy
        accounting=count_request(body,route_counting_policy(binding))
        key='mock-no-credential'
        if self.mode=='api':
            key=os.environ.get(binding['key_env'])
            if not key:raise DynamicError('missing_provider_credential',binding['key_env'])
        with self.lock:
            if self.count>=self.limit:raise DynamicError('provider_request_budget_exhausted','No further request attempts permitted')
            if self.mode=='api':self._reserve_api(binding,body)
            self.count+=1;number=self.count
        started=time.monotonic_ns()
        record={'request_id':request_id,'transport_id':self.transport_id,'attempt_number':number,'kind':self.kind,'source':self.source,
            'synthetic':self.synthetic,'binding_hash':digest(binding),'model_id':binding['model_id'],
            'request_hash':digest(body),'payload':body,'token_accounting':accounting,'status':'submitted','max_retries':0,'cost':None,'usage':None}
        append_jsonl(self.journal,record)
        try:
            reply=self.http(expected,wire['body'],key,timeout)
            # Credential values alone are excluded; benchmark's synthetic secrets remain evidence.
            reply={**reply,'body':reply['body'].replace(key,'[PROVIDER_CREDENTIAL_REMOVED]')}
            reply['headers']={k:v for k,v in reply.get('headers',{}).items() if k.lower() in ('content-type','x-request-id','request-id','retry-after')}
            usage=None
            try:
                if reply['headers'].get('content-type','').startswith('text/event-stream'):
                    for line in reply['body'].splitlines():
                        if line.startswith('data: ') and line[6:]!='[DONE]':usage=json.loads(line[6:]).get('usage') or usage
                else:usage=json.loads(reply['body']).get('usage')
            except ValueError:pass
            self.results[request_id]={'usage':usage,'http_status':reply['status'],'result_unknown':bool(reply.get('read_error'))}
            append_jsonl(self.journal,{**record,'status':'response','response':reply,
                'usage':usage,
                'latency_ns':time.monotonic_ns()-started,'provider_request_id':reply['headers'].get('x-request-id',reply['headers'].get('request-id')),
                'result_unknown':bool(reply.get('read_error'))})
            return reply
        except (OSError,TimeoutError,ValueError) as error:
            append_jsonl(self.journal,{**record,'status':'transport_error','error_type':type(error).__name__,
                'result_unknown':True,'latency_ns':time.monotonic_ns()-started})
            raise DynamicError('provider_transport_unknown','Attempt recorded; no automatic replay or model fallback') from None
