"""Shared Judge field domains and pure full-consumption validation."""
import copy,json
from trustfork.runtime.dynamic.common import DynamicError,digest
FIELD_CONTRACT={
 'trajectory_judgements.*.value':{'domain':'integer_0_to_5_or_unknown_null','status':'complete requires integer; unknown requires null'},
 'claim_lineage.source_claim':{'domain':'claim_id','source':'evidence_index.claims'},
 'claim_lineage.derived_claim':{'domain':'claim_id','source':'evidence_index.claims','constraints':'derived speaker actor and epoch; source before actual input before derived occurrence'},
 'claim_lineage.exposure_ref':{'domain':'request_event_ref','source':'evidence_index.requests.event_ref','constraints':'derived actor and epoch, actual prior source text'},
 'risk_coverage.exposure_request_refs':{'domain':'request_event_ref','source':'evidence_index.requests.event_ref'},
 'opportunity_annotations.visible_request_ref':{'domain':'request_event_ref','source':'evidence_index.requests.event_ref','constraints':'same actor/epoch as decision; decision not before input'},
 'adoptions.actual_request_ref':{'domain':'request_id','source':'evidence_index.requests.request_id','constraints':'consumer actor/epoch, completed actual input contains claim; action must follow input'}
}

def reference_errors(value,index):
 if index is None:return []
 errors=[];claims={c['claim_id'] for c in index['claims']};actions={a['action_id'] for a in index['actions']}
 requests={r['request_id'] for r in index['requests']};refs={r['event_ref'] for r in index['requests']}
 def check(path,actual,domain,allowed):
  if not isinstance(actual,str) or actual not in allowed:errors.append({'path':path,'actual':actual,'expected_domain':domain,'legal_values':sorted(allowed)})
 for group,field,domain,allowed in [('claim_lineage','source_claim','claim_id',claims),('claim_lineage','derived_claim','claim_id',claims),('claim_lineage','exposure_ref','request_event_ref',refs),('adoptions','actual_request_ref','request_id',requests),('adoptions','claim_id','claim_id',claims),('claim_annotations','claim_id','claim_id',claims),('action_annotations','action_id','action_id',actions)]:
  rows=value.get(group,[])
  for i,row in enumerate(rows if isinstance(rows,list) else []):
   if isinstance(row,dict):check(f'$.{group}[{i}].{field}',row.get(field),domain,allowed)
 opportunities=value.get('opportunity_annotations',[])
 for i,row in enumerate(opportunities if isinstance(opportunities,list) else []):
  if isinstance(row,dict) and row.get('opportunity_state')=='present':check(f'$.opportunity_annotations[{i}].visible_request_ref',row.get('visible_request_ref'),'request_event_ref',refs)
 coverage=value.get('risk_coverage',{})
 if isinstance(coverage,dict):
  values=coverage.get('exposure_request_refs',[])
  for i,ref in enumerate(values if isinstance(values,list) else []):check(f'$.risk_coverage.exposure_request_refs[{i}]',ref,'request_event_ref',refs)
 return errors

def decoded_view(prepared):
 from .trajectory_codec import decode_trajectory
 view=json.loads(prepared['wire_payload']['messages'][1]['content'])
 if prepared['representation'] in ('trajectory-lossless-v1','trajectory-lossless-v2'):view=decode_trajectory(view)
 return view

def events_from_prepared(prepared):
 outer=decoded_view(prepared);view=outer.get('trajectory_view',outer);events=[]
 for row in view.get('trajectory',[]):
  if row['event_type']=='tool_operation_finished' and row['payload'].get('receipt'):
   raise DynamicError('judge_validation_context_missing','Original frozen event scope required for tool receipts; never infer missing task/invocation IDs')
  branch,event_id=row['event_ref'].rsplit('::',1)
  events.append({**copy.deepcopy(row),'branch_id':branch,'event_id':event_id,'sequence':row['event_order']+1})
 return events

def validate_complete_result(value,*,pass_name,response_ids=(),evidence_refs=(),scoring_profile='legacy-eight-v1',evidence_index=None,events=None,goal_spec=None,q=None,prepared=None):
 from .judge_client import validate_judge_result,prepared_evidence_index
 if events is not None and prepared is not None and __import__('trustfork.runtime.dynamic.events',fromlist=['events_digest']).events_digest(events)!=prepared['sanitizer']['source_events_hash']:raise DynamicError('judge_validation_source_mismatch','Validation context must be the exact frozen source events')
 if evidence_index is None and prepared is not None:evidence_index=prepared_evidence_index(prepared)
 errors=reference_errors(value,evidence_index) if isinstance(value,dict) else []
 try:validate_judge_result(value,pass_name=pass_name,response_ids=response_ids,evidence_refs=evidence_refs,scoring_profile=scoring_profile,evidence_index=evidence_index)
 except DynamicError as error:
  detail={'path':'$','actual':None,'expected_domain':'Judge schema','code':error.code,'detail':str(error)}
  if error.code=='invalid_anchor':detail['path']='$.trajectory_judgements.'+str(error).split(': ',1)[-1]
  raise DynamicError(error.code,str(error),evidence={'errors':[detail]+errors,'original':error.evidence}) from error
 if errors:raise DynamicError('judge_reference_contract','Invalid reference domains',evidence={'errors':errors})
 if pass_name!='trajectory' or scoring_profile!='dynamic-homogeneous-v2':return value
 if events is None:
  if prepared is None:raise DynamicError('judge_validation_context_missing','Complete consumption requires frozen evidence')
  events=events_from_prepared(prepared)
 from .annotation_contracts import apply_annotations
 from .trajectory_observer import analyze_trajectory
 from .dynamic_metrics_v2 import evaluate_process
 # Every actor is validated; private focal identity is never needed in Judge input.
 try:
  consumed=apply_annotations(analyze_trajectory(events),value,events,goal_spec=goal_spec,evidence_refs=evidence_refs,q=q)
  for actor in ([q] if q is not None else ['Main','A','B','C','D']):evaluate_process(events,consumed['trajectory'],value,actor)
 except DynamicError as error:
  field={'missing_side_effect_evidence':('action_annotations','side_effect_evidence_refs'),'side_effect_epoch_mismatch':('action_annotations','side_effect_evidence_refs'),'side_effect_before_action':('action_annotations','side_effect_evidence_refs'),'side_effect_not_state_evidence':('action_annotations','side_effect_evidence_refs'),'missing_claim_source':('claim_annotations','evidence_refs'),'missing_action_source':('action_annotations','evidence_refs'),'missing_actual_input_evidence':('adoptions','evidence_refs'),'adoption_before_exposure':('adoptions','actual_request_ref'),'lineage_time_or_access_invalid':('claim_lineage','exposure_ref'),'opportunity_visibility_invalid':('opportunity_annotations','visible_request_ref')}.get(error.code)
  path='$.annotations';actual=str(error)
  if field:
   group,key=field;rows=value.get(group,[])
   candidates=[(i,r) for i,r in enumerate(rows) if any(str(v) in str(error) for k,v in r.items() if k in ('action_id','claim_id'))]
   if not candidates:candidates=list(enumerate(rows))
   if candidates:
    i,row=candidates[0];path=f'$.{group}[{i}].{key}';actual=row.get(key)
  raise DynamicError(error.code,str(error),evidence={'errors':[{'path':path,'actual':actual,'expected_domain':'frozen actor/epoch/time/source/effect relationships','code':error.code}]}) from error
 return value
