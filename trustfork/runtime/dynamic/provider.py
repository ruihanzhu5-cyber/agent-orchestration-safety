"""Explicit host HTTP boundary, shared campaign accounting and no hidden retry."""
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

ENGINEERING_SCOPES=('diagnostic','engineering_smoke')
def resolve_provider(config,alias):
    if alias not in ('gpt4o','deepseekflash'):raise DynamicError('unknown_model_alias',alias)
    binding=config.get('logical_bindings',{}).get(alias,{})
    required=('provider','base_url','model_id','key_env','context_window','max_output_tokens','supported_parameters','api','compat','output_token_parameter')
    missing=[alias+'.'+k for k in required if binding.get(k) is None]
    if missing:raise DynamicError('unresolved_provider_binding','No model inference or fallback',evidence=missing)
    if binding['api']!='openai-completions':raise DynamicError('unsupported_provider_api',binding['api'])
    if binding['output_token_parameter'] not in ('max_tokens','max_completion_tokens'):raise DynamicError('unsupported_output_parameter',binding['output_token_parameter'])
    needed=[binding['output_token_parameter']]
    if binding.get('thinking')!='enabled':needed.append('temperature')
    if any(k not in binding['supported_parameters'] for k in needed):raise DynamicError('unsupported_planned_parameter','Mode-specific parameters require explicit support')
    if binding.get('thinking')=='enabled' and binding.get('reasoning_effort')!='high':
        raise DynamicError('unsupported_thinking_configuration','This engineering campaign binds enabled/high explicitly')
    return binding.copy()

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def real_http(url,body,key,timeout):
    started=time.monotonic()
    request=urllib.request.Request(url,data=body.encode(),method='POST',headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
    opener=urllib.request.build_opener(_NoRedirect())
    try:response=opener.open(request,timeout=timeout)
    except urllib.error.HTTPError as error:response=error
    headers={k.lower():v for k,v in response.headers.items() if k.lower() in ('content-type','x-request-id','request-id','retry-after')}
    chunks=[];read_error=False;first_byte=None
    try:
        while True:
            remaining=timeout-(time.monotonic()-started)
            if remaining<=0:raise TimeoutError('total HTTP deadline')
            # urllib's default timeout is per socket operation; also enforce total deadline.
            sock=getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
            if sock is not None:sock.settimeout(remaining)
            chunk=response.read1(65536)
            if not chunk:break
            if first_byte is None:first_byte=time.monotonic()-started
            chunks.append(chunk)
    except (OSError,TimeoutError):read_error=True
    finally:response.close()
    return {'status':response.code,'headers':headers,'body':b''.join(chunks).decode('utf-8',errors='replace'),
        'read_error':read_error,'first_byte_seconds':first_byte,'http_total_seconds':time.monotonic()-started}

class ProviderTransport:
    """Independent request ceiling; all real transports share durable campaign money."""
    def __init__(self,config,*,mode,journal,authorize_real=False,http=None,max_requests=None,kind='model',experiment=None):
        if mode not in ('mock','api'):raise DynamicError('invalid_provider_mode',mode)
        if mode=='mock' and http is None:raise DynamicError('mock_transport_required','Mock must be injected, never external')
        if mode=='api' and (http is not None or not authorize_real or config.get('mode')!='api' or config.get('real_api_enabled') is not True):
            raise DynamicError('real_api_disabled','Explicit API mode, local flag and run authorization required')
        if type(max_requests) is not int or max_requests<1:raise DynamicError('request_budget_required','Explicit request ceiling required')
        self.active_aliases={config['judge_binding']} if kind=='judge' else set(experiment.model_refs.values()) if experiment is not None else set(config['logical_bindings'])
        from .schema import validate_bindings
        validate_bindings(config,formal=False,required_aliases=self.active_aliases)
        self.config,self.mode,self.journal=config,mode,Path(journal)
        if self.journal.exists():raise DynamicError('provider_journal_exists','Select a new attempt; campaign budget is never reset')
        self.scope=config.get('execution_scope','formal')
        if self.scope not in ('formal',*ENGINEERING_SCOPES):raise DynamicError('invalid_execution_scope',self.scope)
        self.transport_id=uuid.uuid4().hex;self.http=http if mode=='mock' else real_http
        self.kind=kind;self.limit=max_requests;self.count=0;self.pending=0;self.lock=threading.RLock()
        self.synthetic=mode=='mock';self.source='mock' if self.synthetic else 'api'
        self.reserved_cost=0;self.window=[];self.results={};self.campaign=None
        if mode=='api' or config.get('campaign_budget'):
            if mode=='api' and self.scope=='formal':validate_bindings(config,formal=True,required_aliases=self.active_aliases)
            elif mode=='api':
                for alias in self.active_aliases:
                    from .model_capabilities import binding_capability
                    c=binding_capability(resolve_provider(config,alias))
                    if c['status'] not in ('declared','verified'):raise DynamicError('provider_capacity_unknown','Engineering needs sourced capacity declaration')
            limits=(config.get('execution_limits') or {}).get(kind)
            required=('max_cost_usd','requests_per_minute','tokens_per_minute','prices_per_million')
            if not isinstance(limits,dict) or any(limits.get(k) is None for k in required):raise DynamicError('execution_limits_unknown','Independent cost/RPM/TPM and route prices required')
            self.limits=limits
            policy=config.get('campaign_budget') or {}
            if not all(policy.get(k) for k in ('path','campaign_id','pricing_basis','conversion_basis','usd_to_cny_upper_bound')):
                raise DynamicError('campaign_pricing_unknown','Evidenced account-route billing and CNY conversion upper bound required')
            # Prices in public default groups are not proof of the actual account route.
            if policy.get('account_price_upper_bound_confirmed') is not True:
                raise DynamicError('campaign_pricing_unknown','Actual account price upper bound or supplier quota required')
            from .campaign_budget import CampaignBudget
            self.campaign=CampaignBudget(policy['path'],campaign_id=policy['campaign_id'],total_cny=policy.get('total_cny',100),phase_limits=policy.get('phase_limits'),must_exist=policy.get('must_exist',False),segment_id=policy.get('segment_id'),segment_cny=policy.get('segment_cny'),segment_identity=policy.get('segment_identity'))
            self.campaign_policy=policy

    def accounting(self,binding,body):
        from .token_accounting import count_request,route_counting_policy,engineering_counting_policy
        policy=engineering_counting_policy(binding) if self.scope in ENGINEERING_SCOPES else route_counting_policy(binding)
        return count_request(body,policy)

    def _reserve_api(self,binding,body,*,request_id,context=None,deadline=None):
        from .model_capabilities import binding_capability
        from .campaign_budget import price_cny
        c=binding_capability(binding);accounting=self.accounting(binding,body)
        n=accounting['estimated_total_input_tokens'];out=body.get(binding['output_token_parameter'])
        engineering=self.scope in ENGINEERING_SCOPES
        if n is None or (not engineering and c['status']!='verified'):raise DynamicError('provider_capacity_unknown','Capacity/counting evidence required')
        margin=max(2048,(n+9)//10) if engineering else 0
        ceiling=c['max_output_tokens']
        if type(out) is not int or out<=0 or out>binding['max_output_tokens'] or (ceiling is not None and out>ceiling) or n+out+margin>c['effective_context_tokens']:
            raise DynamicError('provider_capacity_blocked','Complete input plus reserved output and margin does not fit; no truncation')
        price=self.limits['prices_per_million'].get(binding['model_id'])
        if not isinstance(price,dict):raise DynamicError('provider_price_unknown','Exact wire model price required')
        conversion=price.get('unit_to_cny_upper_bound',self.campaign_policy['usd_to_cny_upper_bound'])
        worst=price_cny(n+margin,out,price,conversion)
        role_cny=self.limits.get('max_cost_cny',float(self.limits['max_cost_usd'])*float(self.campaign_policy['usd_to_cny_upper_bound']))
        if float(worst)>role_cny:
            raise DynamicError('provider_cost_budget_exhausted','Single request exceeds role cost ceiling')
        context=context or {}
        metadata={'run_id':context.get('run_id','diagnostic'),'purpose':context.get('purpose',self.kind),
            'actor_id':context.get('actor_id'),'provider':binding['provider'],'model_id':binding['model_id'],
            'estimated_input_tokens':n,'capacity_margin_tokens':margin,'max_generated_tokens':out,'payload_hash':digest(body),
            'capacity_evidence':c['status'],'execution_scope':self.scope,'pricing_basis':self.campaign_policy['pricing_basis'],
            'source_currency':price.get('source_currency','USD'),'conversion_basis':price.get('conversion_basis',self.campaign_policy['conversion_basis']),
            'usd_to_cny_upper_bound':conversion,'prices_per_million':price,'settlement_basis':'usage_at_evidenced_price_upper_bound',
            'route_fingerprint':c['route_fingerprint'],'kind':self.kind,
            'role_cost_ceiling_cny':role_cny}
        row=self.campaign.reserve(request_id,phase=self.campaign_policy.get('phase','interface_probe'),reserved_cost_cny=worst,metadata=metadata)
        if row['status']!='reserved':raise DynamicError('campaign_attempt_already_recorded','Durable request cannot be replayed')
        wait_started=time.monotonic()
        try:
            while True:
                delay=self.campaign.rate_wait(request_id,route=c['route_fingerprint'],tokens=n+margin+out,
                    rpm=self.limits['requests_per_minute'],tpm=self.limits['tokens_per_minute'])
                if not delay:break
                if deadline is not None and time.monotonic()+delay>=deadline:raise DynamicError('provider_queue_timeout','Wall-clock expires while waiting locally')
                time.sleep(min(delay,1))
            self.campaign.submitted(request_id)
        except BaseException:
            self.campaign.settle(request_id,cancelled_before_send=True)
            raise
        return accounting,metadata,time.monotonic()-wait_started

    def request(self,alias,wire,*,request_id,timeout=None,deadline=None,context=None):
        if alias not in self.active_aliases:raise DynamicError('inactive_provider_alias','Alias outside role scope')
        binding=resolve_provider(self.config,alias)
        expected=binding['base_url'].rstrip('/')+'/chat/completions'
        if wire.get('url')!=expected or wire.get('method')!='POST':raise DynamicError('provider_route_mismatch','Exact configured route required; redirects forbidden')
        body=json.loads(wire['body'])
        if body.get('model')!=binding['model_id']:raise DynamicError('provider_model_mismatch','No model fallback')
        accounting=self.accounting(binding,body)
        timeout=timeout or (self.config.get('runtime_budgets') or {}).get(alias,{}).get('http_timeout_seconds',180)
        deadline=deadline if deadline is not None else time.monotonic()+timeout
        key='mock-no-credential'
        if self.mode=='api':
            key=os.environ.get(binding['key_env'])
            if not key:raise DynamicError('missing_provider_credential','Configured environment variable is empty')
        with self.lock:
            if self.count+self.pending>=self.limit:raise DynamicError('provider_request_budget_exhausted','No further attempts permitted')
            self.pending+=1
        metadata=None;queued=0
        capacity_log=self.journal.with_name('capacity-checks.jsonl')
        check={'request_id':request_id,'transport_id':self.transport_id,'request_context':context or {},'model_id':binding['model_id'],
            'input_tokens_estimated':accounting.get('estimated_total_input_tokens'),'reserved_output_tokens':body.get(binding['output_token_parameter']),
            'payload_hash':digest(body),'source':self.source,'synthetic':self.synthetic}
        if self.campaign:append_jsonl(capacity_log,{**check,'status':'capacity_check_started'})
        try:
            if self.campaign:accounting,metadata,queued=self._reserve_api(binding,body,request_id=request_id,context=context,deadline=deadline)
        except BaseException as error:
            if self.campaign:append_jsonl(capacity_log,{**check,'status':'preflight_blocked','code':getattr(error,'code',type(error).__name__)})
            with self.lock:self.pending-=1
            raise
        with self.lock:self.pending-=1;self.count+=1;number=self.count
        record={'request_id':request_id,'transport_id':self.transport_id,'attempt_number':number,'kind':self.kind,
            'source':self.source,'synthetic':self.synthetic,'binding_hash':digest(binding),'model_id':binding['model_id'],
            'request_hash':digest(body),'payload':body,'token_accounting':accounting,'status':'submitted','max_retries':0,
            'cost':None,'usage':None,'local_queue_seconds':queued,'execution_scope':self.scope,'request_context':context or {}}
        started=time.monotonic_ns()
        try:
            append_jsonl(self.journal,record)
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('request deadline expired')
            reply=self.http(expected,wire['body'],key,min(timeout,remaining))
            reply={**reply,'body':reply['body'].replace(key,'[PROVIDER_CREDENTIAL_REMOVED]')}
            reply['headers']={k:v for k,v in reply.get('headers',{}).items() if k.lower() in ('content-type','x-request-id','request-id','retry-after')}
            usage=None
            try:
                if reply['headers'].get('content-type','').startswith('text/event-stream'):
                    for line in reply['body'].splitlines():
                        if line.startswith('data: ') and line[6:]!='[DONE]':usage=json.loads(line[6:]).get('usage') or usage
                else:usage=json.loads(reply['body']).get('usage')
            except ValueError:pass
            cost=None
            if self.campaign:
                append_jsonl(self.journal,{**record,'status':'response_received','response':reply,'usage':usage})
                valid=isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens'))
                if valid and not reply.get('read_error'):
                    from .campaign_budget import price_cny
                    cost=price_cny(usage['prompt_tokens'],usage['completion_tokens'],metadata['prices_per_million'],metadata['usd_to_cny_upper_bound'])
                    try:self.campaign.settle(request_id,settled_cost_cny=cost,usage=usage)
                    except DynamicError:
                        self.campaign.pause(metadata['route_fingerprint'],'price_or_usage_bound_breached')
                        self.campaign.settle(request_id,usage=usage)
                        raise
                    if usage['prompt_tokens']>metadata['estimated_input_tokens']+metadata['capacity_margin_tokens']:
                        self.campaign.pause(metadata['route_fingerprint'],'input_estimate_margin_exceeded')
                else:self.campaign.settle(request_id,usage=usage)
            self.results[request_id]={'usage':usage,'http_status':reply['status'],'result_unknown':bool(reply.get('read_error')),'cost_cny':float(cost) if cost is not None else None}
            append_jsonl(self.journal,{**record,'status':'response','response':reply,'usage':usage,
                'cost_cny':float(cost) if cost is not None else None,'latency_ns':time.monotonic_ns()-started,
                'provider_request_id':reply['headers'].get('x-request-id',reply['headers'].get('request-id')),'result_unknown':bool(reply.get('read_error'))})
            return reply
        except BaseException as error:
            if self.campaign:
                rows={r['request_id']:r for r in self.campaign.rows()}
                if rows[request_id]['status']=='submitted':self.campaign.settle(request_id)
            append_jsonl(self.journal,{**record,'status':'transport_error','error_type':type(error).__name__,'code':getattr(error,'code',None),
                'result_unknown':True,'latency_ns':time.monotonic_ns()-started})
            if isinstance(error,DynamicError):raise
            raise DynamicError('provider_transport_unknown','Attempt retained; no automatic replay') from None
