"""Read-only diagnostics from actual request, capacity, event and money receipts."""
import json
from pathlib import Path
from collections import Counter,defaultdict
from .common import read_json
from .campaign_budget import CampaignBudget
from trustfork.tools.audit_model_calls import audit_transport_journals

def lines(p):
 return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]

def generation(reply):
 body=reply.get('body','');usage=None;finish=None
 if reply.get('headers',{}).get('content-type','').startswith('text/event-stream'):
  chunks=[]
  for line in body.splitlines():
   if line.startswith('data: ') and line[6:]!='[DONE]':
    try:chunks.append(json.loads(line[6:]))
    except ValueError:continue
 else:
  try:chunks=[json.loads(body)]
  except ValueError:chunks=[]
 for chunk in chunks:
  if not isinstance(chunk,dict):continue
  usage=chunk.get('usage') or usage
  for choice in chunk.get('choices',[]):
   finish=choice.get('finish_reason') or finish
 return finish,usage

def analyze_campaign(root):
 root=Path(root)
 journals=[p for p in root.rglob('*.jsonl') if p.name in ('provider-requests.jsonl','judge-requests.jsonl')]
 audit=audit_transport_journals(journals)
 attempts={};responses={}
 for p in journals:
  for row in lines(p):
   key=(row.get('transport_id'),row.get('request_id'))
   if row.get('status')=='submitted':attempts[key]=row
   if row.get('status') in ('response_received','response'):responses[key]=row
 finishes=Counter();per_actor={};timings=[];unknown_finish=0
 for key,row in attempts.items():
  reply=responses.get(key,{});finish,usage=generation(reply.get('response',{}))
  if finish:finishes[finish]+=1
  else:unknown_finish+=1
  context=row.get('request_context') or {}
  actor=context.get('actor_id') or ('Judge' if row.get('kind')=='judge' else 'unscoped_probe')
  group=row.get('model_id','unknown')+'|'+actor
  stats=per_actor.setdefault(group,{'max_actual_wire_input_estimate':None,'completion_tokens_reported':0,'reasoning_tokens_reported':0,'usage_missing_requests':0,'requests':0})
  stats['requests']+=1
  n=(row.get('token_accounting') or {}).get('estimated_total_input_tokens')
  if n is not None:stats['max_actual_wire_input_estimate']=max(n,stats['max_actual_wire_input_estimate'] or 0)
  if isinstance(usage,dict):
   stats['completion_tokens_reported']+=usage.get('completion_tokens') or 0
   details=usage.get('completion_tokens_details') or {}
   stats['reasoning_tokens_reported']+=details.get('reasoning_tokens') or usage.get('reasoning_tokens') or 0
  else:stats['usage_missing_requests']+=1
  raw=reply.get('response') or {}
  timings.append({'request_id':row['request_id'],'local_queue_seconds':reply.get('local_queue_seconds',row.get('local_queue_seconds')),
   'remote_first_byte_seconds':raw.get('first_byte_seconds'),'remote_total_seconds':raw.get('http_total_seconds'),'result_unknown':reply.get('result_unknown',key not in responses)})
 checks={};blocked={}
 for p in root.rglob('capacity-checks.jsonl'):
  for row in lines(p):
   k=(row['transport_id'],row['request_id'])
   if row['status']=='capacity_check_started':checks[k]=row
   elif row['status']=='preflight_blocked':blocked[k]=row
 capacity={k:r for k,r in blocked.items() if r.get('code') in ('provider_capacity_blocked','judge_input_overflow')}
 events={}
 for p in root.rglob('events.jsonl'):
  for e in lines(p):events[(e['branch_id'],e['event_id'])]=e
 truncations=[]
 for e in events.values():
  if e['event_type']=='tool_visibility':
   result=e['payload'].get('result') or {};details=result.get('details') or {}
   if (details.get('truncation') or {}).get('truncated') or any(details.get(k) is True for k in ('lineLimitReached','matchLimitReached','linesTruncated')):
    truncations.append({'event_ref':e['branch_id']+'::'+e['event_id'],'actor':e.get('actor_id'),'name':e['payload'].get('name'),'details':details})
 runs=[]
 for p in root.rglob('run.json'):
  v=read_json(p)
  if v.get('run_id'):runs.append(v)
 resources=Counter()
 resource_codes={'output_limit','provider_capacity_blocked','time_limit','team_budget','campaign_cost_exhausted','campaign_phase_cost_exhausted','provider_queue_timeout','request_exceeds_tpm','provider_route_paused'}
 for r in runs:
  reason=r.get('termination_reason')
  if r.get('run_status')=='resource_ended' or reason in resource_codes:resources[reason or 'unknown']+=1
 mailbox=Counter();delivery_keys=set()
 for p in root.rglob('delivery_receipts.json'):
  v=read_json(p)
  for message in v.get('messages',[]):
   for recipient,state in message.get('delivery',{}).items():
    key=(str(p.parent),message['message_id'],recipient)
    if key not in delivery_keys:delivery_keys.add(key);mailbox[state.get('status','unknown')]+=1
 judge_passes=[]
 for p in root.rglob('*-prepared.json'):
  if not p.name.startswith(('response-','trajectory-')):continue
  prepared=read_json(p)
  if prepared.get('not_applicable'):continue
  result=p.with_name(p.name.replace('-prepared.json','-result.json'))
  v=read_json(result) if result.exists() else {}
  judge_passes.append({'source':str(p.relative_to(root)),'valid':isinstance(v.get('result'),dict),'structure_attempts':v.get('structure_attempts')})
 ledger_path=root/'campaign-budget.sqlite3'
 budget=CampaignBudget(ledger_path,campaign_id='first-api-20261026') if ledger_path.exists() else None
 rows=budget.rows() if budget else []
 estimation=[]
 for row in rows:
  usage=row.get('usage') or {};n=usage.get('prompt_tokens')
  if type(n) is int:
   m=row['metadata'];estimation.append({'request_id':row['request_id'],'estimated':m.get('estimated_input_tokens'),'actual_usage':n,
    'margin':m.get('capacity_margin_tokens'),'difference_actual_minus_estimate':n-m['estimated_input_tokens']})
 return {'version':'first-api-diagnostics-v1','actual_call_audit':audit,'finish_reasons':dict(finishes),
  'truncation_rate':{'numerator':finishes['length'],'denominator':sum(finishes.values()),'unknown_finish_requests':unknown_finish},
  'capacity_refusal_rate':{'numerator':len(capacity),'denominator':len(checks),'scope':'Unique transport/request preflight checks; pre-send attempts, never confirmed exposure'},
  'preflight_blocked_codes':dict(Counter(r.get('code') for r in blocked.values())),
  'resource_termination_rate':{'numerator':sum(resources.values()),'denominator':len(runs),'reasons':dict(resources),'scope':'Started T3 run.json records; prefix-only failures and histories reported separately'},
  'per_actor':per_actor,'timings':timings,'token_estimate_vs_usage':estimation,
  'tool_truncations_observed':truncations,'tool_truncation_coverage':'Original Pi details only; missing metadata does not prove no truncation',
  'message_recipient_states':dict(mailbox),'message_scope':'Retained per-run delivery receipts; each (run,message_id,recipient) once',
  'judge_valid_return_rate':{'numerator':sum(p['valid'] for p in judge_passes),'denominator':len(judge_passes),
   'first_attempt_valid':sum(p['valid'] and p['structure_attempts']==1 for p in judge_passes),'after_repair_valid':sum(p['valid'] and p['structure_attempts']==2 for p in judge_passes)},
  'judge_passes':judge_passes,'budget':budget.summary() if budget else None,
  'cost_note':'settled_cny is usage at evidenced peak/uncached upper bound, not a reconciled invoice; unknown charges retain reservations',
  'global_historical_call_count':'unknown; campaign audit does not reclassify old third-party account bills'}
