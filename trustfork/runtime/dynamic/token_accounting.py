"""Network-free decoded-request estimates. No HTTP escaping or route inference."""
from .common import canonical,digest,DynamicError
VERSION='decoded-request-count-v1'
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
 counts={'text':0,'tool_calls':0,'tool_results':0,'tools_schema':0,'response_format':0,'role_and_call_associations':0}
 def count(value):return counter(value if isinstance(value,str) else canonical(value).decode())
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
 return {'version':VERSION,'input_tokens':tokens,'components':counts,'framing_tokens':framing,
  'estimated_total_input_tokens':tokens+framing if framing is not None else None,
  'route_fingerprint':p.get('route_fingerprint'),'tokenizer':p.get('tokenizer'),'policy_source':p.get('source'),'policy_evidence_hash':p.get('evidence_hash'),
  'policy_status':p.get('status','unknown'),'wire_serialization_is_input':False,'method':'decoded text/tool/schema BPE estimate plus explicit role/call associations and separately evidenced route framing; not observed usage'}
