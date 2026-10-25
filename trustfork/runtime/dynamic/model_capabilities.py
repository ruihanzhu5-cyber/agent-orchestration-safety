"""Evidence-bound effective endpoint capacity. Logical aliases imply nothing."""
from .common import DynamicError,digest


def unknown_capability():
    return {'status':'unknown','effective_context_tokens':None,'max_output_tokens':None,
        'source':None,'evidence_hash':None,'verified_at':None,'route_fingerprint':None,
        'tokenizer':None,'framing_tokens':None,'output_token_parameter':None}


def validate_capability(value):
    if set(value)!=set(unknown_capability()) or value['status'] not in ('unknown','declared','verified'):
        raise DynamicError('invalid_capability','Unexpected capability fields/status')
    for name in ('effective_context_tokens','max_output_tokens','framing_tokens'):
        n=value[name]
        if n is not None and (type(n) is not int or n<(0 if name=='framing_tokens' else 1)):
            raise DynamicError('invalid_capability',name)
    tokenizer=value['tokenizer']
    if tokenizer is not None and (not isinstance(tokenizer,dict) or set(tokenizer)!={'id','version','count_method','applicable_route'} or
            any(not isinstance(v,str) or not v for v in tokenizer.values())):
        raise DynamicError('invalid_capability','Tokenizer provenance is incomplete')
    if value['status'] in ('declared','verified'):
        required=('source','evidence_hash','route_fingerprint')
        if value['status']=='verified':required+=('verified_at',)
        if any(not isinstance(value[k],str) or not value[k] for k in required) or value['effective_context_tokens'] is None:
            raise DynamicError('invalid_capability','Capacity lacks route-specific evidence')
        if tokenizer and tokenizer['applicable_route']!=value['route_fingerprint']:
            raise DynamicError('invalid_capability','Tokenizer belongs to a different route')
    return value


def binding_capability(binding):
    capability=validate_capability(binding.get('capability',unknown_capability()))
    if capability['status']!='unknown':
        route=digest({k:binding.get(k) for k in ('provider','base_url','model_id')})
        if capability['route_fingerprint']!=route:raise DynamicError('capability_route_mismatch','Capacity is for a different endpoint/model')
    return capability
