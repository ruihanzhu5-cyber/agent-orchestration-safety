"""Network-free decoded-request estimates. No HTTP escaping or route inference."""
from .common import canonical,digest,DynamicError
VERSION='decoded-request-count-v2'
def route_counting_policy(binding,*,counter=None):
 from .model_capabilities import binding_capability
 cap=binding_capability(binding);tokenizer=cap.get('tokenizer');route=digest({k:binding.get(k) for k in ('provider','base_url','model_id')})
 policy={'version':VERSION,'route_fingerprint':route,'tokenizer':tokenizer,'framing_tokens':cap.get('framing_tokens'),'source':cap.get('source'),'evidence_hash':cap.get('evidence_hash'),'status':cap['status']}
 if counter is not None:policy['counter']=counter;return policy
 if not tokenizer or tokenizer.get('applicable_route')!=route:raise DynamicError('request_counting_policy_unknown','Route-specific tokenizer evidence required')
 if tokenizer['count_method']=='fixture-exact' and tokenizer['id'] in ('fixture','supplied-test-counter'):policy['counter']=len
 elif tokenizer['id']=='o200k_base':
  import importlib.metadata
  if tokenizer['version']!=importlib.metadata.version('tiktoken'):raise DynamicError('tokenizer_version_mismatch','Pinned installed tokenizer differs')
  from trustfork.scoring.judge_request import offline_counter
  policy['counter']=offline_counter()
 else:raise DynamicError('request_counting_policy_unknown','No registered offline tokenizer for this exact route')
 return policy
def count_request(wire_payload,route_counting_policy):
 p=route_counting_policy;counter=p.get('counter')
 if not callable(counter):raise DynamicError('request_counting_policy_unknown','Explicit offline counter required')
 body=wire_payload
 if isinstance(body,dict) and 'body' in body:
  import json
  body=json.loads(body['body'])
 counts={'text':0,'reasoning':0,'tool_calls':0,'tool_results':0,'tools_schema':0,'response_format':0,'role_and_call_associations':0}
 decoded_bytes=0
 def count(value):
  nonlocal decoded_bytes
  text=value if isinstance(value,str) else canonical(value).decode()
  decoded_bytes+=len(text.encode('utf-8'))
  return counter(text)
 def content(value):
  if value is None:return 0
  if isinstance(value,str):return count(value)
  if isinstance(value,list):
   total=0
   for block in value:
    if not isinstance(block,dict) or block.get('type') not in ('text','input_text') or not isinstance(block.get('text'),str):raise DynamicError('request_image_count_unknown','Preserve unknown multimodal input; do not send')
    total+=count(block['text'])
   return total
  raise DynamicError('request_content_invalid','Expected text, null or pure-text blocks')
 for m in body.get('messages',[]):
  if not isinstance(m,dict) or not isinstance(m.get('role'),str):raise DynamicError('request_message_invalid','Role required')
  counts['role_and_call_associations']+=count({k:m[k] for k in ('role','name','tool_call_id') if k in m})
  counts['tool_results' if m['role']=='tool' else 'text']+=content(m.get('content'))
  if 'reasoning_content' in m:counts['reasoning']+=content(m['reasoning_content'])
  calls=m.get('tool_calls',[])
  if not isinstance(calls,list):raise DynamicError('request_tool_calls_invalid','Expected tool calls array')
  for call in calls:
   function=call.get('function',{})
   if not isinstance(function.get('name'),str) or not isinstance(function.get('arguments'),str):raise DynamicError('request_tool_calls_invalid','Exact function name and argument text required')
   counts['tool_calls']+=count(function['name'])+count(function['arguments'])
   counts['role_and_call_associations']+=count({k:call[k] for k in ('id','type') if k in call})
 if body.get('tools'):counts['tools_schema']=count(body['tools'])
 if body.get('response_format'):counts['response_format']=count(body['response_format'])
 tokens=sum(counts.values());framing=p.get('framing_tokens')
 return {'version':VERSION,'decoded_input_utf8_bytes':decoded_bytes,'service_prompt_tokens':None,'input_tokens':tokens,'components':counts,'framing_tokens':framing,
  'estimated_total_input_tokens':tokens+framing if framing is not None else None,
  'route_fingerprint':p.get('route_fingerprint'),'tokenizer':p.get('tokenizer'),'policy_source':p.get('source'),'policy_evidence_hash':p.get('evidence_hash'),
  'policy_status':p.get('status','unknown'),'wire_serialization_is_input':False,'method':'UTF-8 byte estimate plus fixed engineering framing; additional margin applied at sender; not server token count' if p.get('tokenizer',{}).get('id')=='utf8-byte-upper-estimate' else 'decoded text/tool/schema BPE estimate plus explicit role/call associations and separately evidenced route framing; not observed usage'}

def engineering_counting_policy(binding):
 """Explicit byte estimate for declared-capacity engineering only, never verified."""
 from .model_capabilities import binding_capability
 cap=binding_capability(binding)
 if cap['status'] not in ('declared','verified'):raise DynamicError('provider_capacity_unknown','Sourced declaration required')
 route=cap['route_fingerprint']
 selected=binding.get('engineering_counting')
 if selected is not None:
  if selected!='deepseek-v41-text-v1':raise DynamicError('request_counting_policy_unknown',selected)
  return deepseek_text_policy(binding,cap)
 return {'version':VERSION,'counter':lambda s:len(s.encode('utf-8')),
  'tokenizer':{'id':'utf8-byte-upper-estimate','version':'v1','count_method':'conservative-estimate','applicable_route':route},
  'framing_tokens':64,'route_fingerprint':route,'source':cap['source'],'evidence_hash':cap['evidence_hash'],'status':'estimated'}

def deepseek_text_policy(binding,cap):
 """Pinned official tokenizer; route-specific engineering estimate, never exact API usage."""
 import os,importlib.metadata,hashlib
 from pathlib import Path
 from functools import lru_cache
 from .common import read_json,config_dir,repo_root
 spec=read_json(config_dir()/'tokenizers.v1.json')['deepseek-v41-text-v1']
 if binding.get('provider')!=spec['provider'] or binding.get('base_url','').rstrip('/')!=spec['base_url'] or binding.get('model_id') not in spec['model_ids']:
  raise DynamicError('counting_route_mismatch','Tokenizer is not registered for this exact provider route')
 version=importlib.metadata.version(spec['library'])
 if version!=spec['library_version']:raise DynamicError('tokenizer_version_mismatch','Pinned tokenizers library differs')
 path=Path(os.environ.get('TRUSTFORK_DEEPSEEK_TOKENIZER',str(repo_root()/spec['cache_relative'])))
 counter=_deepseek_counter(str(path.resolve()),spec['sha256'])
 return {'version':VERSION,'counter':counter,'tokenizer':{'id':'deepseek-v41-text-v1','version':version,'sha256':spec['sha256'],
    'count_method':'official-tokenizer-decoded-text-estimate','applicable_route':cap['route_fingerprint']},
    'framing_tokens':spec['framing_tokens'],'route_fingerprint':cap['route_fingerprint'],
    'source':spec['source'],'evidence_hash':digest(spec),'status':'estimated'}

from functools import lru_cache
@lru_cache(maxsize=2)
def _deepseek_counter(path,expected_hash):
 import hashlib
 from pathlib import Path
 from tokenizers import Tokenizer
 p=Path(path)
 if not p.is_file():raise DynamicError('offline_tokenizer_unavailable','Pinned DeepSeek tokenizer must be prepared locally')
 if hashlib.sha256(p.read_bytes()).hexdigest()!=expected_hash:raise DynamicError('tokenizer_hash_mismatch','Pinned tokenizer data differs')
 tokenizer=Tokenizer.from_file(str(p))
 return lambda text:len(tokenizer.encode(text,add_special_tokens=False).ids)
