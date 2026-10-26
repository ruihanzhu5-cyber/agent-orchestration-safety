"""Deterministic white-list review copy; original evidence is never edited."""
import base64,csv,hashlib,io,json,re,sqlite3,posixpath,tempfile,shutil,os
from pathlib import Path
from .artifacts import safe_slug
from .common import DynamicError,canonical,file_hash,read_json

VERSION='dynamic-review-export-v4'
FOLLOWUP_ROOT_FILES={'tests.md','execution-attempt.json','formal-plan.json','formal-judge-acceptance.json','execution-results.json','gpt-rescore-results.json','deepseek-results.json','review-findings.md','test-results.json','regression-matrix.csv','resource-replay.json','offline-chain-results.json','resume-dry-run.json','ledger-migration.json','metrics.csv','segment.json','budget-summary.json','input-size-audit.json','input-size-audit-initial.json','tokenizer-provenance.json','offline-acceptance.json','parent-frozen-seal.json','baseline-source-hashes.json'}
ROOT_FILES=FOLLOWUP_ROOT_FILES|{'campaign.json','plan.jsonl','resolved-config.json','results.json','cost-summary.json'}
ROLE_DIRS={'blocks','history','probes','diagnostics','test-results','analysis','fixtures','gpt-rescore','deepseek','actions','tests'}
RUNTIME_NAMES={'run.json','run_manifest.json','events.jsonl','prefix-events.json','delivery_receipts.json',
 'history-bundle-reuse.jsonl','pass-states.json','attempt-summary.json','trajectory-output-estimate.json','trajectory-output-estimate-error.json','origin.json','private_bindings.json','profile_metadata.json','history.json','history-execution.json','history-bundle.json',
 'partial-state.json','prefix-outcome.json','block.json','provider-requests.jsonl','judge-requests.jsonl',
 'judge-capacity-calibrations.jsonl','task-completion.json','copy-manifest.json','history-compatibility.json','preparation-outcome.json','transport-metrics.json','judge-structure-repairs.jsonl','capacity-checks.jsonl','scoring_annotations.json','partial_annotations.json'}
PRIVATE_FIELDS={'authorization','cookie','set-cookie','access_token','refresh_token','key_env'}
def sha(data):return hashlib.sha256(data).hexdigest()
def jsonlines(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []

class Redactor:
 def __init__(self,secrets=(),private_paths=()):
  self.secrets=sorted({s for s in secrets if isinstance(s,str) and s},key=lambda s:(-len(s),s))
  self.paths=sorted({str(p) for p in private_paths if str(p)},key=lambda s:(-len(s),s));self.changes=[]
 def text(self,s,ref):
  for i,secret in enumerate(self.secrets,1):
   if secret in s:
    s=s.replace(secret,f'[REDACTED_CREDENTIAL_{i:03d}]')
    self.changes.append({'reference':ref,'reason':'known_real_credential','placeholder':i})
  for i,p in enumerate(self.paths,1):
   if p in s:
    s=s.replace(p,f'[LOCAL_PRIVATE_PATH_{i:03d}]');self.changes.append({'reference':ref,'reason':'real_local_path','placeholder':i})
  def header(m):
   self.changes.append({'reference':ref,'reason':'authentication_header'})
   return m.group(1)+'[REDACTED_AUTH_HEADER]'
  return re.sub(r'(?im)^(\s*(?:authorization|cookie|set-cookie)\s*:\s*)[^\r\n]*',header,s)
 def value(self,v,ref):
  if isinstance(v,dict):
   out={}
   for k,item in v.items():
    out_key=self.text(k,ref+'/dictionary-key')
    if out_key in out:raise DynamicError('review_redaction_key_collision','Distinct dictionary keys would merge')
    if k.lower() in PRIVATE_FIELDS and item is not None:
     out[out_key]='[REDACTED_PRIVATE_FIELD]';self.changes.append({'reference':ref+'/'+out_key,'reason':'authentication_field'})
    elif k in ('content_b64','data') and isinstance(item,str):
     try:raw=base64.b64decode(item,validate=True);text=raw.decode()
     except (ValueError,UnicodeError):out[out_key]=self.value(item,ref+'/'+out_key)
     else:
      text2=self.text(text,ref+'/'+out_key)
      out[out_key]=base64.b64encode(text2.encode()).decode() if text2!=text else item
    else:out[out_key]=self.value(item,ref+'/'+out_key)
   return out
  if isinstance(v,list):return [self.value(x,ref+'/'+str(i)) for i,x in enumerate(v)]
  if isinstance(v,str):
   if v.lstrip().startswith(('{','[')):
    try:parsed=json.loads(v)
    except ValueError:pass
    else:
     changed=self.value(parsed,ref+'/decoded-json')
     return canonical(changed).decode() if changed!=parsed else v
   return self.text(v,ref)
  return v
 def scan(self,data):
  if any(s.encode() in data for s in self.secrets):raise DynamicError('review_secret_scan_failed','Known credential remains; do not publish')

def allowed(p,root):
 rel=p.relative_to(root)
 if p.is_symlink() or p.name.startswith('.env') or p.name in ('auth.json','models-cache.json','config.json'):return False
 if p.suffix not in ('.json','.jsonl','.csv','.md','.txt'):return False
 if len(rel.parts)==1:return p.name in ROOT_FILES
 if rel.parts[0] not in ROLE_DIRS:return False
 if rel.parts[0] in ('probes','diagnostics','test-results','analysis','fixtures','actions','tests'):return True
 return (p.name in RUNTIME_NAMES or p.name.endswith(('-prepared.json','-result.json','-error.json')) or
  (p.name.startswith(('prepared_','history-bundle','prefix-')) and p.suffix=='.json') or
  (p.name.startswith(('provider-requests-relay-','judge-requests-relay-')) and p.suffix=='.jsonl') or
  any(s in rel.parts for s in ('scoring','scoring-versions','operation-evidence')) or ('control' in rel.parts and p.suffix=='.jsonl'))

def csv_text(fields,rows):
 out=io.StringIO();w=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');w.writeheader()
 for row in rows:w.writerow({k:canonical(v).decode() if isinstance(v,(dict,list)) else v for k,v in row.items() if k in fields})
 return out.getvalue()

def state_difference(before,after,red,reference):
 from trustfork.scoring.goal_observer import frozen_workspace
 try:
  a=frozen_workspace(before);b=frozen_workspace(after)
 except (DynamicError,OSError,KeyError) as error:
  return {'observation_status':'unknown','reason':getattr(error,'code',type(error).__name__),'filesystem_changes':None,
   'scope':'Original archive unavailable or invalid; no invented unchanged/absent facts'}
 complete=a.get('consistent_cutoff') and b.get('consistent_cutoff')
 changes=[]
 for path in sorted(set(a['paths'])|set(b['paths'])):
  left=a['paths'].get(path);right=b['paths'].get(path)
  clean=lambda value:{k:v for k,v in (value or {}).items() if k!='evidence_ref'}
  if clean(left)!=clean(right):changes.append({'path':path,'before':left,'after':right})
 value={'observation_status':'observed' if complete else 'partial_or_unknown','filesystem_changes':changes if complete else None,
  'before':{k:v for k,v in a.items() if k!='paths'},'after':{k:v for k,v in b.items() if k!='paths'},
  'before_path_index':{k:{n:v for n,v in row.items() if n!='content_b64'} for k,row in a['paths'].items()},
  'after_path_index':{k:{n:v for n,v in row.items() if n!='content_b64'} for k,row in b['paths'].items()},
  'scope':'Captured workspace/service/home assets only; full changed file bytes preserved as Base64. Original archives remain local. Not a RAM snapshot.'}
 return red.value(value,reference)

def export_campaign(source,destination,*,secrets=(),private_paths=(),snapshot=False,max_part_bytes=5*1024*1024,max_total_bytes=50*1024*1024,ledger_path=None,ledger_segment_id=None,ledger_attempt_id=None):
 source=Path(source).resolve();destination=Path(destination).resolve()
 if source==destination or source in destination.parents or destination in source.parents:raise DynamicError('review_export_overlaps_source','Share copy must be outside originals')
 campaign=read_json(source/'campaign.json')
 if campaign.get('status')=='open' and not snapshot:raise DynamicError('review_campaign_not_stopped','Seal campaign or explicitly select partial snapshot')
 if max_part_bytes<100:raise DynamicError('review_part_size_invalid','Part limit too small')
 candidates=sorted(p for p in source.rglob('*') if p.is_file() and allowed(p,source))
 before={p.relative_to(source).as_posix():file_hash(p) for p in candidates}
 destination.parent.mkdir(parents=True,exist_ok=True)
 staging=tempfile.TemporaryDirectory(prefix='.review-spool-',dir=destination.parent)
 from .review_spool import ReviewFiles
 red=Redactor(secrets,(*private_paths,str(source)));files=ReviewFiles(Path(staging.name)/'leaves',red.scan);mappings=[];excluded=[];events={}
 def put(name,data):
  raw=data.encode() if isinstance(data,str) else data
  if name in files and files[name]!=raw:raise DynamicError('review_export_collision',name)
  red.scan(raw);files[name]=raw
 def parts(prefix,rows):
  names=[];chunk=[];size=0
  for i,row in enumerate(rows):
   raw=canonical(row)+b'\n'
   if len(raw)>max_part_bytes:
    name=prefix+f'.large-{i:06d}.json';put(name,canonical(row)+b'\n')
    raw=canonical({'large_record_ref':name,'export_hash':sha(files[name]),'original_sequence':row.get('sequence')})+b'\n'
   if chunk and size+len(raw)>max_part_bytes:
    name=prefix+f'.part-{len(names):04d}.jsonl';put(name,b''.join(chunk));names.append(name);chunk=[];size=0
   chunk.append(raw);size+=len(raw)
  if chunk or not names:
   name=prefix+f'.part-{len(names):04d}.jsonl';put(name,b''.join(chunk));names.append(name)
  return names
 runs=[];history_indices=[]
 for p in candidates:
  if p.name=='run.json':
   run=read_json(p)
   if isinstance(run,dict) and run.get('run_id'):
    runs.append((p,run,'trajectories/'+safe_slug(str(run.get('block_id',run['run_id']))+'|'+str(run.get('condition'))+'|'+run['run_id'])))
 def mapped(rel):
  rel=Path(rel).as_posix()
  path=source/rel
  if rel in FOLLOWUP_ROOT_FILES:return rel
  for p,run,prefix in runs:
   if path.parent==p.parent or p.parent in path.parents:return prefix+'/'+path.relative_to(p.parent).as_posix()
  return 'evidence/'+rel
 for p in candidates:
  rel=p.relative_to(source).as_posix();target=mapped(rel)
  try:
   if p.suffix=='.jsonl':
    if p.suffix=='.jsonl':
     # History/prefix shards need no retained in-memory conversation index.
     # Stream every row, preserving byte order and the same stable redaction refs.
     def stream_rows(path=p,reference=rel):
      with path.open() as lines:
       for i,line in enumerate(lines):
        if not line.strip():continue
        value=red.value(json.loads(line),reference+'/'+str(i))
        if path.name=='events.jsonl' and path.parent not in events:events[path.parent]=[value]
        yield value
     if p.name=='events.jsonl' and any(p.parent==run_file.parent for run_file,_,_ in runs):
      # Bind the source per view; do not capture loop variables for later conversations.
      class EventRows:
       def __init__(self,path,reference):self.path,self.reference=path,reference
       def __iter__(self):
        with self.path.open() as lines:
         for i,line in enumerate(lines):
          if line.strip():yield red.value(json.loads(line),self.reference+'/'+str(i))
      rows=EventRows(p,rel);events[p.parent]=rows
     else:rows=stream_rows()
    names=parts(target.removesuffix('.jsonl'),rows)
   elif p.suffix=='.json':
    put(target,canonical(red.value(read_json(p),rel))+b'\n');names=[target]
   else:put(target,red.text(p.read_text(),rel));names=[target]
  except (ValueError,UnicodeError) as error:
   excluded.append({'source':rel,'reason':'unreadable_text_or_json','error_type':type(error).__name__});continue
  mappings.append({'source_path':rel,'source_hash':before[rel],'source_size':p.stat().st_size,
   'exports':[{'path':n,'export_hash':sha(files[n]),'size':len(files[n])} for n in names]})
 for p in source.rglob('*'):
  if p.is_symlink():excluded.append({'source':p.relative_to(source).as_posix(),'reason':'symlink_not_followed'})
  elif p.is_file() and not allowed(p,source):excluded.append({'source':p.relative_to(source).as_posix(),'reason':'outside_explicit_text_whitelist_original_retained_locally'})
 plans=red.value(jsonlines(source/'plan.jsonl'),'plan')
 resolved=read_json(source/'results.json') if (source/'results.json').exists() else {}
 outcome_rows=resolved.get('plan_results',[]) if isinstance(resolved,dict) else []
 outcomes={v['plan_id']:v for v in outcome_rows if v.get('plan_id')}
 plans=[{**v,'initial_status':v.get('status'),**red.value(outcomes.get(v.get('plan_id'),{}),'plan-status')} for v in plans]
 put('plan.jsonl',b''.join(canonical(p)+b'\n' for p in plans));results=[]
 for p,run,prefix in runs:
  run=red.value(run,p.relative_to(source).as_posix());rows=events.get(p.parent,[])
  def conversation_rows():
   yield f"# {run['run_id']}\n\nStatus: {run.get('run_status','unknown')}\n\n"
   seen=set()
   for e in rows:
    key=(e.get('branch_id'),e.get('event_id'))
    if key in seen:raise DynamicError('review_duplicate_event_id',str(key))
    seen.add(key)
    if e.get('event_type') in ('model_request_submitted','model_response','message_enqueued','tool_visibility','pi_event'):
     yield f"## {e.get('sequence')} · {e.get('event_type')} · actor={e.get('actor_id')} · request={e.get('request_id')} · event={e.get('event_id')}\n\n~~~json\n"
     yield json.dumps(e['payload'],ensure_ascii=False,indent=2)
     yield '\n~~~\n\n'
  files.put_stream(prefix+'/conversation.md',conversation_rows())
  names=parts(prefix+'/requests',(e for e in rows if e.get('event_type') in ('provider_payload','model_response')))
  metric=p.parent/'scoring'/'run_summary.json'
  put(prefix+'/metrics.json',canonical(red.value(read_json(metric),str(metric.relative_to(source))) if metric.exists() else {'value':None,'status':'not_annotated','reason':'No completed scoring artifact'})+b'\n')
  frozen=run.get('frozen_export')
  state=state_difference(run.get('prefix_export'),frozen,red,prefix+'/state-diff')
  state['run_export_ref']=mapped(p.relative_to(source).as_posix())
  put(prefix+'/state-diff.json',canonical(state)+b'\n')
  put(prefix+'/README.md',f"# {run['run_id']}\n\nCondition: {run.get('condition')}; protocol: {run.get('protocol')}; model: {run.get('team_model',run.get('main_model'))}.\n\nStatus: {run.get('run_status')}; termination: {run.get('termination_reason')}.\n\n[Conversation](conversation.md) · [Metrics](metrics.json) · [State observation](state-diff.json)\n\nRequest/response shards: "+', '.join('['+Path(n).name+']('+Path(n).name+')' for n in names)+"\n\nFull events, Judge records and source mappings are indexed in the campaign manifest.\n")
  result_row={k:run.get(k) for k in ('run_id','case_id','team_model','main_model','protocol','condition','run_status','termination_reason','completion_status')}
  result_row.update(kind='t3',billing_run_id=run['run_id'],metric_summary=read_json(metric).get('scores') if metric.exists() else None,
   observation_complete=read_json(metric).get('observation_complete') if metric.exists() else None,
   unknown_reason=None if metric.exists() else 'No completed scoring artifact')
  match=next((v for v in outcome_rows if v.get('run_id')==run['run_id']),{})
  if match.get('unknown_reason'):result_row['unknown_reason']=match['unknown_reason']
  origin=p.parent/'origin.json'
  result_row['behavior_execution_sha']=read_json(origin).get('behavior_execution_sha') if origin.exists() else campaign.get('identity',{}).get('commit')
  result_row['scoring_execution_sha']=campaign.get('identity',{}).get('commit')
  if match.get('kind')=='rescore':result_row['kind']='rescore'
  for field in ('scoring_pass_states','process_annotation_status','unknown_reason'):
   if field in match:result_row[field]=match[field]
  results.append(result_row)
 for p in candidates:
  if p.name=='history-execution.json':
   raw=read_json(p);v=red.value(raw,str(p.relative_to(source)))
   rel=p.relative_to(source)
   team=rel.parts[1] if len(rel.parts)>1 and rel.parts[1] in ('gpt4o','deepseekflash') else None
   if rel.parts[0]=='deepseek':team='deepseekflash'
   results.append({'run_id':v.get('history_id'),'case_id':v.get('task_id'),'team_model':team,'run_status':v.get('status'),'kind':'history','billing_run_id':next((e.get('branch_id') for e in events.get(p.parent,[]) if e.get('branch_id')),None),'source_ref':mapped(rel)})
   slug='history/'+safe_slug(str(v.get('history_id')))
   put(slug+'-state-diff.json',canonical(state_difference(raw.get('initial_state'),raw.get('frozen_state'),red,str(rel)+'/state-diff'))+b'\n')
   base=mapped((p.parent/'events.jsonl').relative_to(source).as_posix()).removesuffix('.jsonl')
   parts_found=sorted(n for n in files if n.startswith(base+'.part-') and n.endswith('.jsonl'))
   history_indices.append(slug+'/README.md')
   put(slug+'/README.md',f"# History {v.get('history_id')}\n\nCase {v.get('task_id')}; model {team}; status {v.get('status')}. Status is not a judged task-success claim.\n\n[Execution record]("+posixpath.relpath(mapped(rel),slug)+") · [Captured state difference]("+posixpath.relpath(slug+'-state-diff.json',slug)+")\n\nComplete ordered event/tool/model-view records:\n\n"+'\n'.join('- ['+Path(n).name+']('+posixpath.relpath(n,slug)+')' for n in parts_found)+'\n')

 started={(r.get('case_id'),r.get('team_model') or r.get('main_model'),r.get('protocol'),r.get('condition')) for r in results}
 for plan in plans:
  if plan.get('kind') in ('t3','history','rescore') and (plan.get('case_id'),plan.get('team_model'),plan.get('protocol'),plan.get('condition')) not in started:
   results.append({**plan,'run_status':plan.get('run_status','not_started'),'termination_reason':plan.get('not_started_reason',plan.get('reason','not_started'))})
 costs=[];db_path=Path(ledger_path) if ledger_path is not None else source/'campaign-budget.sqlite3'
 if ledger_path is not None and not db_path.is_file():raise DynamicError('review_original_ledger_missing','Explicit original ledger not found')
 if db_path.exists():
  with sqlite3.connect('file:'+str(db_path)+'?mode=ro',uri=True) as db:
   db.row_factory=sqlite3.Row
   for row in db.execute('SELECT * FROM requests ORDER BY updated_at,request_id'):
    v=dict(row);v.update(json.loads(v.pop('metadata')))
    if ledger_segment_id is not None and v.get('segment_id')!=ledger_segment_id:continue
    if ledger_attempt_id is not None and v.get('execution_attempt_id')!=ledger_attempt_id:continue
    v['reserved_cost_cny']=v.pop('reserved')/1e6
    settled=v.pop('settled');v['settled_cost_cny']=settled/1e6 if settled is not None else None
    costs.append(red.value(v,'costs/'+v['request_id']))
 for result in results:
  rows=[c for c in costs if result.get('billing_run_id') and c.get('run_id')==result['billing_run_id']]
  result['direct_requests']=sum(c.get('submitted_at') is not None for c in rows)
  result['direct_settled_cny_upper']=sum(c['settled_cost_cny'] or 0 for c in rows if c['status']=='settled')
  result['direct_unknown_reserved_cny']=sum(c['reserved_cost_cny'] for c in rows if c['status'] in ('submitted','charge_unknown','reserved'))
  result['cost_scope']='Direct run plus Judge only; shared history/prefix/probe costs remain separate ledger rows; never multiply them per branch'
 put('results.csv',csv_text(['kind','run_id','case_id','team_model','main_model','protocol','condition','run_status','termination_reason','completion_status','source_ref','observation_complete','unknown_reason','metric_summary','behavior_execution_sha','scoring_execution_sha','scoring_pass_states','process_annotation_status','direct_requests','direct_settled_cny_upper','direct_unknown_reserved_cny','cost_scope'],results))
 put('costs.csv',csv_text(['request_id','segment_id','execution_attempt_id','execution_stage_id','execution_review_id','kind','submitted_at','run_id','phase','purpose','actor_id','provider','model_id','status','estimated_input_tokens','max_generated_tokens','reserved_cost_cny','settled_cost_cny','usage','pricing_basis','source_currency','conversion_basis','settlement_basis'],costs))
 config=source/'resolved-config.json'
 put('config.redacted.json',canonical(red.value(read_json(config),'config') if config.exists() else {'status':'not_resolved','real_api_enabled':False})+b'\n')
 tests=[(p.relative_to(source).as_posix(),mapped(p.relative_to(source).as_posix())) for p in candidates if p.relative_to(source).parts[0]=='test-results']
 if 'tests.md' not in files:put('tests.md','# Test evidence\n\n'+('\n'.join('- ['+a+']('+b+')' for a,b in tests) if tests else 'No retained test receipt; no pass claimed.')+'\n\nActual Docker tests, mock responses and real probes are separate evidence scopes.\n')
 links='\n'.join('- ['+red.text(r['run_id'],'index')+']('+prefix+'/README.md)' for _,r,prefix in runs)
 history_links='\n'.join('- ['+Path(n).parent.name+']('+n+')' for n in history_indices)
 overview='\n\nRecorded plan outcomes: '+json.dumps(resolved.get('plan_counts',{}),sort_keys=True)+'. Completed histories are unjudged execution endings, not demonstrated task successes.\n\n'
 if (source/'cost-summary.json').exists():
  money=read_json(source/'cost-summary.json')
  overview+='CNY accounting upper bound / unknown reservation / remaining: '+json.dumps(money.get('guard',{}),sort_keys=True)+'. Supplier invoice reconciliation remains unknown.\n\n'
 overview+='[Probe comparison](evidence/probes/summary.json) · [Request diagnostics](evidence/diagnostics/first-api-diagnostics.json) · [Formal report](../../../docs/dynamic-join/Runtime_Budget_And_First_API_Report_20261026.md)\n\n## Retained histories\n\n'+history_links+'\n\n## T3 trajectories\n\n'
 if campaign.get('parent_campaign_id'):
  overview='\n\nParent campaign: '+campaign['parent_campaign_id']+'; previous behavior and new scorer versions are separate. New segment CNY20 ceiling is included in the original CNY100, never reset.\n\n[Segment provenance](segment.json) · [Input size audit](input-size-audit.json) · [Formal fixtures](evidence/fixtures/summary.json) · [Report](../../../docs/dynamic-join/Plan_Judge_Followup_Report_20261026.md)\n\n## Retained histories\n\n'+history_links+'\n\n## Frozen and new trajectories\n\n'
 if campaign.get('review_id')=='runtime-judge-review-20261026':
  overview='\n\nOriginal CNY100 campaign and existing CNY20 segment are inherited. This publication contains this execution attempt only in costs.csv; whole-ledger and prior spend remain in budget-summary.json.\n\n[Review findings](review-findings.md) · [Regression matrix](regression-matrix.csv) · [Resource replay](resource-replay.json) · [Offline full chain](offline-chain-results.json) · [Attempt/migration dry-run](resume-dry-run.json) · [Formal Judge acceptance](formal-judge-acceptance.json) · [Metrics with statuses](metrics.csv) · [Report](../../../docs/dynamic-join/Runtime_Judge_Review_Fixes_20261026.md)\n\n## Retained histories\n\n'+history_links+'\n\n## Frozen and new trajectories\n\n'
 put('README.md',f"# {campaign.get('campaign_id',source.name)}\n\nStatus: {campaign.get('status')}; "+('explicit partial snapshot' if snapshot else 'stopped campaign')+f".\n\nExecution code SHA: {campaign.get('identity',{}).get('commit','unknown')}.\n\nCampaign ceiling CNY100; interface_probe sub-ceiling CNY20 is included. Consult costs.csv and diagnostics for settlement and unknown charges. Engineering smoke is not a main experiment.\n\n[Plan](plan.jsonl) · [Results](results.csv) · [Costs](costs.csv) · [Tests](tests.md) · [Configuration](config.redacted.json) · [Manifest](manifest.json)\n\nRecorded T3 runs: {len(runs)}; plan rows: {len(plans)}. Unstarted items are retained.\n\n"+overview+links+"\n\nOriginal binary archives/databases remain local. Selected complete text evidence is shared; exclusions and distinct source/export hashes are recorded in manifest.json.\n")
 if before!={p.relative_to(source).as_posix():file_hash(p) for p in sorted(source.rglob('*')) if p.is_file() and allowed(p,source)}:raise DynamicError('review_source_changed','Stop writers or use a new snapshot')
 # Leaves were already compressed as soon as each shard completed.
 files,renames,packing=files.finalize()
 for row in mappings:
  for item in row['exports']:
   item['path']=renames.get(item['path'],item['path']);item.update(files.stored_info(item['path']))
 if files.stored_total()>max_total_bytes:raise DynamicError('review_export_size_exceeded','Lossless packing exceeds publication limit; retain all evidence locally')
 manifest={'version':VERSION,'campaign_id':campaign.get('campaign_id',source.name),'execution_code_sha':campaign.get('identity',{}).get('commit'),
  'exporter_source_hash':file_hash(Path(__file__)),'snapshot':snapshot,'snapshot_boundary':{'source_files':before,'campaign_status':campaign.get('status')},'source_export_mapping':mappings,
  'redactions':red.changes,'missing_or_excluded':excluded,'binary_exclusion_policy':['environment archives','databases','dependencies','caches','unlisted file types'],
  'files':[files.stored_info(n) for n in sorted(files)],'size_bytes_excluding_manifest':files.stored_total(),'streaming_memory':{'uncompressed_shards_retained':0,'max_part_bytes':max_part_bytes,'max_leaf_bytes':files.max_leaf,'storage':'disk compressed at shard completion; one decoded shard/record at a time'},
  'known_credential_scan':'passed','human_diff_review_required':True,'packing':packing}
 put('manifest.json',canonical(manifest)+b'\n')
 if files.stored_total()>max_total_bytes:raise DynamicError('review_export_size_exceeded','Manifest included exceeds publication limit')
 if destination.exists():
  actual={p.relative_to(destination).as_posix():{'size':p.stat().st_size,'hash':file_hash(p)} for p in destination.rglob('*') if p.is_file()}
  expected={n:{'size':m['stored_size'],'hash':m['stored_hash']} for n,m in files.meta.items()}
  if actual!=expected:raise DynamicError('review_export_exists_changed','Choose a new explicit publication version')
  staging.cleanup();return manifest
 publish=Path(staging.name)/'publish';publish.mkdir()
 for name,m in files.meta.items():
  p=publish/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(m['disk'],p)
  if file_hash(p)!=m['stored_hash']:raise DynamicError('review_export_write_mismatch',name)
  with p.open('rb') as stream:os.fsync(stream.fileno())
 # Completion becomes visible only after all files and manifest are verified.
 os.rename(publish,destination)
 staging.cleanup();return manifest
