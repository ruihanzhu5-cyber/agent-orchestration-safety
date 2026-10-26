"""Offline request-log audit. Run-level fixed zero fields are never evidence."""
import argparse,json
from collections import Counter
from pathlib import Path
from trustfork.runtime.dynamic.common import canonical,digest,file_hash,read_json,write_json,repo_root


def audit_request_events(events):
    unique={};compact={};conflicts=[];total=0
    for event in events:
        total+=1;identity=event['branch_id']+'::'+event['event_id'];hashed=digest(event)
        if identity in unique and unique[identity]!=hashed:conflicts.append(identity)
        unique[identity]=hashed
        kind=event['event_type']
        if kind in ('model_request_submitted','judge_request_submitted','judge_attempt_submitted','model_response'):
            payload=event['payload']
            small={'response':{'provider':(payload.get('response') or {}).get('provider')}} if kind=='model_response' else {k:payload.get(k) for k in ('synthetic','execution_backend','provider')}
            compact[identity]={'branch_id':event['branch_id'],'event_id':event['event_id'],'request_id':event['request_id'],'event_type':kind,'payload':small}
        else:compact.pop(identity,None)
    rows=list(compact.values());responses={(e['branch_id'],e['request_id']):e['payload'].get('response') or {}
        for e in rows if e['event_type']=='model_response'}
    counts=Counter();provider_counts=Counter();request_records=[]
    for event in rows:
        kind=event['event_type']
        if kind=='model_request_submitted':
            response=responses.get((event['branch_id'],event['request_id']),{})
            provider=response.get('provider');provider_counts[provider or 'unresolved']+=1
            backend=event['payload'].get('execution_backend')
            classification='scripted' if (provider=='scripted' or backend in ('mock','scripted-test')) and event['payload'].get('synthetic') is True else 'real' if provider and provider!='scripted' else 'unresolved'
            counts[classification+'_model_attempts']+=1
            request_records.append({'attempt_key':event['branch_id']+'::'+(event['request_id'] or event['event_id']),
                'kind':'model','classification':classification,'provider':provider,'evidence_ref':event['branch_id']+'::'+event['event_id']})
        if kind in ('judge_request_submitted','judge_attempt_submitted'):
            classification='scripted' if event['payload'].get('synthetic') is True else 'real' if event['payload'].get('synthetic') is False else 'unresolved'
            counts[classification+'_judge_attempts']+=1
            request_records.append({'attempt_key':event['branch_id']+'::'+(event['request_id'] or event['event_id']),
                'kind':'judge','classification':classification,'provider':event['payload'].get('provider'),
                'evidence_ref':event['branch_id']+'::'+event['event_id']})
    return {'unique_events':len(unique),'duplicate_event_records':total-len(unique),'event_conflicts':conflicts,
        'model_provider_counts':dict(provider_counts),
        'request_records':request_records,
        **{k:counts[k] for k in ('scripted_model_attempts','real_model_attempts','unresolved_model_attempts','scripted_judge_attempts','real_judge_attempts','unresolved_judge_attempts')},
        'real_model_calls_in_observed_scope':None if counts['unresolved_model_attempts'] or conflicts else counts['real_model_attempts'],
        'real_judge_calls_in_observed_scope':None if conflicts or counts['unresolved_judge_attempts'] else counts['real_judge_attempts'],
        'counts_include_submitted_attempts_even_without_success':True}


def audit_guard_records(records):
    unique={};conflicts=[]
    for row in records:
        key=row['rpc_id'];value={k:v for k,v in row.items() if k!='receipt_file_sha256'}
        if key in unique and unique[key]!=value:conflicts.append(key)
        unique[key]=value
    rows=list(unique.values())
    return {'raw_receipts':len(records),'unique_rpc_receipts':len(rows),'duplicate_receipts':len(records)-len(rows),
        'conflicting_rpc_ids':conflicts,
        'incomplete_guard_receipts':sum(not {'network_attempts','blocked_host_fs','blocked_host_exec'}<=set(r['guard']) for r in rows),
        'scripted_execute_turn_receipts':sum(r.get('mode')=='scripted-test' and r['operation']=='execute_turn' for r in rows),
        'positive_network_attempt_receipts':sum(bool(r['guard'].get('network_attempts')) for r in rows),
        'host_io_violation_receipts':sum(bool(r['guard'].get('blocked_host_fs') or r['guard'].get('blocked_host_exec')) for r in rows),
        'initialized_real_request_counters_used_as_proof':False,
        'note':'Guard real_model_requests/real_judge_requests are initialization fields; use actual provider events. Network counters are cumulative; positive receipt count is not a unique request count.'}


def audit_transport_journals(paths):
    """Count host HTTP attempts, including failures and independent Judge passes."""
    attempts={};conflicts=[];errors=[];hashes={}
    for path in sorted(set(paths)):
        try:
            hashes[str(path)]=file_hash(path)
            for line in path.open():
                row=json.loads(line)
                if row.get('status')!='submitted':continue
                identity=(row.get('transport_id',str(path)),row.get('kind'),row.get('request_id'),row.get('attempt_number'))
                if identity in attempts and attempts[identity]!=row:conflicts.append(list(identity))
                attempts[identity]=row
        except (ValueError,OSError):errors.append(str(path))
    values=list(attempts.values())
    unresolved=sum(row.get('source') not in ('api','mock') or not isinstance(row.get('synthetic'),bool)
        or (row.get('source')=='api')==row.get('synthetic') for row in values)
    return {'unique_http_attempts':len(values),'real_model_requests':None if unresolved or conflicts or errors else
        sum(r['source']=='api' and r['kind']=='model' for r in values),
        'real_judge_requests':None if unresolved or conflicts or errors else sum(r['source']=='api' and r['kind']=='judge' for r in values),
        'mock_attempts':sum(r['source']=='mock' for r in values),'conflicts':conflicts,'unresolved':unresolved,
        'errors':errors,'source_file_hashes':hashes,'counted_from_submissions_not_initialized_counters':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,action='append',required=True)
    p.add_argument('--guard-archive',type=Path,action='append',default=[]);p.add_argument('--coverage-gap',action='append',default=[])
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    event_streams=[];guards=[];sources={};errors=[];actual_runs=0;seen_paths=set();journals=[]
    def read_lines(path):
        sources[str(path)]=file_hash(path)
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    def stream_events(path):
        with path.open() as lines:
            for line in lines:
                if line.strip():yield json.loads(line)
    for root in a.root:
        for path in sorted(root.rglob('run.json')):
            run=read_json(path)
            if not {'run_manifest_path','run_id','run_status','events_path','prefix_events_path'}<=set(run):continue
            actual_runs+=1
            for name in (run['events_path'],run['prefix_events_path']):
                log=path.parent/name
                if log in seen_paths:continue
                seen_paths.add(log)
                if not log.exists():errors.append({'run_id':run['run_id'],'reason':'missing_request_event_log'});continue
                try:
                    sources[str(log)]=file_hash(log)
                    event_streams.append(read_json(log) if log.suffix=='.json' else stream_events(log))
                except (ValueError,OSError):errors.append({'run_id':run['run_id'],'reason':'unreadable_event_log'})
        for path in sorted(root.rglob('network-guard.jsonl')):
            if path in seen_paths:continue
            seen_paths.add(path);guards.extend(read_lines(path))
        for name in ('provider-requests.jsonl','judge-requests.jsonl'):journals.extend(root.rglob(name))
    for path in a.guard_archive:guards.extend(read_lines(path))
    from itertools import chain
    calls=audit_request_events(chain.from_iterable(event_streams));guard=audit_guard_records(guards)
    report={'version':'actual-request-call-audit-v2','actual_run_records':actual_runs,'calls':calls,'guard_receipts':guard,
        'transport_call_audit':audit_transport_journals(journals),
        'source_file_hashes':sources,'coverage_gaps':a.coverage_gap,'log_errors':errors,
        'complete_historical_model_call_total':None if a.coverage_gap or errors else calls['real_model_calls_in_observed_scope'],
        'complete_historical_judge_call_total':None if a.coverage_gap or errors else calls['real_judge_calls_in_observed_scope'],
        'scope':'Retained actual run/prefix request events; standalone scripted bridge executions independently audited with guard receipts',
        'run_metadata_zero_fields_used_as_proof':False,'keys_or_env_values_read':False,'formal_ready':False}
    write_json(a.out,report)
    print(json.dumps({'actual_run_records':actual_runs,'observed_model_calls':calls['real_model_calls_in_observed_scope'],
        'observed_judge_calls':calls['real_judge_calls_in_observed_scope'],'coverage_gaps':len(a.coverage_gap),
        'scripted_turn_receipts':guard['scripted_execute_turn_receipts'],'positive_network_receipts':guard['positive_network_attempt_receipts']}))


if __name__=='__main__':main()
