"""Operation transport and completion are evidence, never goal judgments."""
from pathlib import PurePosixPath
from .common import DynamicError


def make_operation_receipt(operation_id,operation,args,raw_result,*,scope=None,
        transport_status='complete',error=None,raw_result_ref=None,started_event_ref=None,
        interval=None,overlaps=(),cancel_requested=False):
    scope=scope or {};value=raw_result
    if isinstance(value,dict) and 'frames' in value:
        ends=[frame.get('result') for frame in value['frames'] if frame.get('kind')=='exit']
        value=ends[0] if len(ends)==1 else None
    if isinstance(value,dict) and value.get('kind')=='exit':value=value.get('result')
    value=value if isinstance(value,dict) else {}
    process=operation.startswith('process.')
    code=value.get('exitCode') if process else None
    if isinstance(code,bool) or (code is not None and not isinstance(code,int)):code=None
    timed_out=value.get('timed_out') is True
    cancelled=(value.get('cancelled_before_start') is True or value.get('cancelled') is True or
        (cancel_requested and code is not None and code<0))
    status='unknown'
    if cancelled:status='cancelled'
    elif error is not None:
        if isinstance(error,DynamicError) and error.code.startswith('remote_'):
            transport_status='complete';status='failed'
        else:transport_status='unknown'
    elif transport_status=='complete':
        if timed_out:status='failed'
        elif process and code is not None:
            program=PurePosixPath((args.get('argv') or [''])[0]).name
            status='succeeded' if code==0 or (program in ('rg','grep') and code==1) else 'failed'
        elif not process and operation.startswith('fs.') and isinstance(raw_result,dict) and raw_result:
            status='failed' if raw_result.get('error') else 'succeeded'
    return {'schema_version':'2.0','operation_id':operation_id,'actor_id':scope.get('actor_id'),
        'request_id':scope.get('request_id'),'invocation_id':scope.get('invocation_id'),
        'operation':operation,'transport_status':transport_status,'operation_status':status,
        'process_exit_code':code,'timed_out':timed_out,'cancelled':cancelled,
        'effect_status':'unknown' if transport_status!='complete' else 'not_assessed',
        'raw_result_ref':raw_result_ref,'started_event_ref':started_event_ref,
        'observation_interval':interval,'overlapping_operation_ids':list(overlaps)}


def legacy_receipt(begin,end):
    payload=end['payload'] if end else {}
    if 'receipt' in payload:
        from .schema import validate_contract
        receipt=payload['receipt'];validate_contract('OperationReceipt',receipt)
        if receipt['operation_id']!=begin['tool_call_id'] or any(
                receipt[k]!=begin.get(k) for k in ('actor_id','request_id','invocation_id')):
            raise DynamicError('operation_receipt_scope_mismatch','Receipt belongs to another operation/actor/request')
        return receipt,'2.0'
    key='result' if 'result' in payload else 'exit' if 'exit' in payload else None
    raw=payload.get(key) if key else None
    scope={k:begin.get(k) for k in ('actor_id','request_id','invocation_id')}
    reference=lambda event:event['branch_id']+'::'+event['event_id']
    receipt=make_operation_receipt(begin['tool_call_id'],begin['payload']['operation'],
        begin['payload']['args'],raw,scope=scope,
        transport_status='complete' if key else 'unknown',
        raw_result_ref=reference(end)+'#/payload/'+key if key else None,
        started_event_ref=reference(begin),interval=payload.get('observation_interval'),
        overlaps=payload.get('overlapping_operation_ids',[]))
    return receipt,'legacy-'+key+'-v1' if key else 'legacy-unresolved-v1'
