"""Continuously dispatch Pi RPC while each actor's one-turn call is pending."""
from __future__ import annotations
import concurrent.futures
import errno
import json
import os
import subprocess
import threading
import uuid
import time
from pathlib import Path

from .common import DynamicError, canonical, digest
from .schema import validate_contract


class PiClient:
    def __init__(self, root, environment, *, ledger=None, coordination=None, observer=None,provider=None,model_refs=None):
        self.root, self.environment = Path(root).resolve(), environment
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger, self.coordination = ledger, coordination
        self.observer=observer
        self.provider=provider;self.model_refs=model_refs or {}
        self.mode=provider.mode if provider else 'scripted-test'
        runtime = Path(__file__).parent
        node = Path(os.environ.get('TRUSTFORK_NODE_BIN', str(Path.home()/'.local/share/trustfork-env/node-v24.15.0-linux-x64/bin/node')))
        if not node.is_file():
            raise DynamicError('missing_locked_node', 'Set TRUSTFORK_NODE_BIN to audited Linux Node 24.15.0')
        self.pending, self.scopes, self.sessions = {}, {}, {}
        self.request_deadlines={}
        self.lock, self.write_lock = threading.RLock(), threading.RLock()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=12, thread_name_prefix='pi-rpc')
        self.stderr_file = (self.root/'bridge.stderr.log').open('w')
        spool = self.root/'spool'
        spool.mkdir(exist_ok=True)
        self.process = subprocess.Popen([str(node), str(runtime/'pi_bridge.ts')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr_file, text=True, bufsize=1, cwd=runtime,
            env={'PATH':str(node.parent)+':/usr/bin:/bin', 'LANG':'C.UTF-8', 'TMPDIR':str(spool), 'PI_OFFLINE':'1'})
        from .rpc_spool import RpcSpool
        self.rpc_spool=RpcSpool(self.root/'rpc-inbound.spool')
        self.returned_results=0;self.transport_failure=None
        self.processor=threading.Thread(target=self._process_frames,daemon=True,name='pi-ordered-evidence')
        self.reader = threading.Thread(target=self._read, daemon=True,name='pi-durable-ingress')
        self.processor.start();self.reader.start()
        self.closed = False
        self.cleanup_errors=[]

    def _write(self, row):
        with self.write_lock:
            if self.process.poll() is not None:
                raise DynamicError('bridge_exited', str(self.process.returncode))
            self.process.stdin.write(canonical(row).decode()+'\n')
            self.process.stdin.flush()

    def _read(self):
        error=None
        try:
            for line in self.process.stdout:self.rpc_spool.append(line)
        except (OSError,ValueError,DynamicError) as caught:error=caught
        finally:self.rpc_spool.finish(error)

    def _process_frames(self):
        try:
            for line,end in self.rpc_spool.frames_iter():
                row=json.loads(line)
                if row.get('kind')=='result':
                    with self.lock:
                        future=self.pending.pop(row['rpc_id'],None)
                        scope=self.scopes.pop(row['rpc_id'],None)
                        if scope and scope['operation']=='execute_turn':self.request_deadlines.pop(scope['request_id'],None)
                    if future is None:raise DynamicError('unknown_bridge_result',row['rpc_id'])
                    if row.get('error'):
                        error=row['error'];future.set_exception(DynamicError(error.get('code','pi_bridge_error'),error.get('message','Bridge error')) if isinstance(error,dict) else DynamicError('pi_bridge_error',error))
                    else:future.set_result(row['payload'])
                    self.returned_results+=1
                elif row.get('kind')=='event':
                    if row.get('operation') in ('model_request_submitted','pi_event','provider_payload','tool_visibility'):self._handle_event(row)
                    else:self.executor.submit(self._handle_event,row)
                else:raise DynamicError('invalid_bridge_frame',str(row.get('kind')))
                self.rpc_spool.acknowledge(end)
        except (OSError,ValueError,DynamicError) as error:
            self.transport_failure=error
            self.rpc_spool.finish(error);self._fail_pending(error)
        finally:self._fail_pending(DynamicError('bridge_transport_closed','Pi transport closed before a response'))

    def _fail_pending(self, error):
        with self.lock:
            for future in self.pending.values():
                if not future.done(): future.set_exception(error)
            self.pending.clear(); self.scopes.clear()

    def _validate_scope(self, row):
        with self.lock:
            active = [x for x in self.scopes.values() if x['opaque_session_id']==row['opaque_session_id']
                      and x['request_id']==row['request_id'] and x['operation'] in ('execute_turn','probe_tool')]
        fields = ('actor_id','branch_id','task_id','stage_id','stage_epoch','invocation_id')
        if len(active)!=1 or any(row[k]!=active[0][k] for k in fields):
            raise DynamicError('rpc_scope_mismatch', 'Late or cross-branch/actor tool callback')

    def _handle_event(self, row):
        try:
            self._validate_scope(row)
            operation, payload = row['operation'], row['payload']
            if operation in ('model_request_submitted','pi_event','provider_payload','tool_visibility'):
                if operation=='tool_visibility' and self.ledger:
                    ids=['op_'+digest({'session':row['opaque_session_id'],'request':row['request_id'],'op':op}) for op in payload['raw_operation_ids']]
                    raw=[e for e in self.ledger.iter_events(event_type='tool_operation_finished') if e['event_type']=='tool_operation_finished' and e.get('tool_call_id') in ids]
                    payload={**payload,'raw_operation_ids':ids,
                        'raw_result_refs':[e['payload']['receipt']['raw_result_ref'] for e in raw],
                        'raw_event_refs':[e['branch_id']+'::'+e['event_id'] for e in raw],
                        'visibility_policy':'Pi-0.84.1-original-result-no-automatic-full-output-injection'}
                if self.ledger:
                    self.ledger.append(operation, payload, actor_id=row['actor_id'], stage_id=row['stage_id'],
                        stage_epoch=row['stage_epoch'], request_id=row['request_id'], invocation_id=row['invocation_id'])
                return
            identity = 'op_' + digest({'session':row['opaque_session_id'],'request':row['request_id'],'op':payload.get('op_id')})
            scope={k:row[k] for k in ('actor_id','stage_id','stage_epoch','request_id','invocation_id')}
            if operation=='provider_http':
                if self.provider is None:raise DynamicError('real_api_disabled','No explicit provider backend')
                alias=self.model_refs[row['actor_id']]
                result=self.provider.request(alias,payload,request_id=row['request_id'],
                    deadline=self.request_deadlines.get(row['request_id']),
                    context={'actor_id':row['actor_id'],'run_id':row['branch_id'],
                        'purpose':'history' if row['branch_id'].startswith('history_') else 'team'})
            elif operation == 'tool_operation':
                try:result = self.environment.exec_work_operation(payload['operation'],payload['args'],identity,scope=scope)
                finally:self._observe_operation(row,identity,payload['operation'],payload['args'])
            elif operation == 'tool_stream':
                try:
                    for frame in self.environment.stream_work_operation(payload['args'],identity,scope=scope):
                        self._write({'kind':'host_response','rpc_id':row['rpc_id'],'frame':frame})
                finally:self._observe_operation(row,identity,'process.stream',payload['args'])
                result = {'status':'complete'}
            elif operation == 'tool_cancel':
                result = self.environment.cancel_operation(identity)
            elif operation == 'coordination_tool':
                if self.coordination is None:
                    raise DynamicError('missing_coordination_handler', payload['name'])
                result = self.coordination(row['actor_id'],payload['name'],payload['args'],row)
            else:
                raise DynamicError('unknown_bridge_event', operation)
            self._write({'kind':'host_response','rpc_id':row['rpc_id'],'payload':result})
        except (OSError, ValueError, DynamicError, subprocess.SubprocessError) as error:
            if row['operation'] in ('model_request_submitted','pi_event','provider_payload','tool_visibility'):
                self._fail_pending(error)
            else:
                number = error.evidence.get('errno') if isinstance(error,DynamicError) and isinstance(error.evidence,dict) else None
                self._write({'kind':'host_response','rpc_id':row['rpc_id'],
                    'error':{'message':str(error),'code':errno.errorcode.get(number) if number else error.code if isinstance(error,DynamicError) else None}})

    def _observe_operation(self,row,identity,operation,args):
        if not self.observer or operation not in ('fs.write','process.bash','process.argv','process.stream'):return
        try:self.observer(row,identity,operation,args)
        except Exception as error:
            # A passive measurement failure is explicit, and cannot turn a
            # completed work operation into a different tool response/retry.
            if self.ledger:self.ledger.append('passive_observer_error',{'status':'unknown','operation_id':identity,
                'error_type':type(error).__name__,'reason':str(error)},actor_id=row['actor_id'],
                stage_id=row['stage_id'],stage_epoch=row['stage_epoch'],request_id=row['request_id'])

    def call(self, session_id, operation, payload=None, *, request_id=None, stage_id='initial', epoch=0, invocation_id=None, timeout=180):
        config = self.sessions[session_id]
        if operation=='execute_turn':self.request_deadlines[request_id]=time.monotonic()+timeout
        envelope = {'rpc_id':uuid.uuid4().hex,'opaque_session_id':session_id,'actor_id':config['actor_id'],
                    'branch_id':config['branch_id'],'task_id':config['task_id'],'stage_id':stage_id,'stage_epoch':epoch,
                    'request_id':request_id,'invocation_id':invocation_id,'operation':operation,'payload':payload or {}}
        future = concurrent.futures.Future()
        validate_contract('BridgeEnvelope',envelope)
        with self.lock:
            self.pending[envelope['rpc_id']], self.scopes[envelope['rpc_id']] = future, envelope
        self._write(envelope)
        try:
            result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as error:
            # No automatic re-execution: a whole batch may already have effects.
            cancel = {**envelope,'rpc_id':uuid.uuid4().hex,'operation':'cancel','payload':{}}
            with self.lock:
                self.pending[cancel['rpc_id']],self.scopes[cancel['rpc_id']]=concurrent.futures.Future(),cancel
            self._write(cancel)
            raise DynamicError('pi_turn_effect_unknown', 'Timed out after permit; tool effects require reconciliation') from error
        if isinstance(result,dict) and 'guard' in result:
            with (self.root/'network-guard.jsonl').open('ab') as receipts:
                receipts.write(canonical({'rpc_id':envelope['rpc_id'],'operation':operation,'actor_id':config['actor_id'],
                    'request_id':request_id,'guard':result['guard'],'mode':self.mode})+b'\n')
            if any(result['guard'][k] for k in ('network_attempts','blocked_host_fs','blocked_host_exec')):
                raise DynamicError('isolation_trap_failed', 'A host task IO or network attempt was trapped', evidence=result['guard'])
        if operation=='close':self.sessions.pop(session_id,None)
        return result

    def create_session(self, actor_id, *, branch_id, task_id, system_prompt, task_resources=None, task_home='/root', snapshot=None):
        identity = uuid.uuid4().hex
        self.sessions[identity]={'actor_id':actor_id,'branch_id':branch_id,'task_id':task_id}
        payload = {'mode':self.mode,'system_prompt':system_prompt,'task_resources':task_resources or [],
                   'task_home':task_home,'control_dir':str(self.root/'sessions'/identity)}
        if self.provider:
            from .provider import resolve_provider
            binding=resolve_provider(self.provider.config,self.model_refs[actor_id])
            payload['provider_binding']={k:v for k,v in binding.items() if k!='key_env'}
        if snapshot is not None: payload['snapshot']=snapshot
        return identity,self.call(identity,'restore_session' if snapshot else 'create_session',payload)

    def close(self):
        if self.closed:return
        for identity in list(self.sessions):
            if self.process.poll() is None:
                try:self.call(identity,'close',timeout=10)
                except (DynamicError, OSError, subprocess.SubprocessError) as error:
                    self.cleanup_errors.append({'session_id':identity,'reason':str(error)})
                    if self.ledger:self.ledger.append('session_cleanup_failed',self.cleanup_errors[-1])
        self.process.stdin.close()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        self.reader.join(timeout=10);self.processor.join(timeout=10)
        from .common import write_json
        stats={**self.rpc_spool.stats(),'returned_results':self.returned_results,'bridge_exit_code':self.process.returncode,'reader_alive':self.reader.is_alive(),'processor_alive':self.processor.is_alive(),'transport_failure':getattr(self.transport_failure,'code',None)}
        write_json(self.root/'transport-metrics.json',stats)
        self.executor.shutdown(wait=True,cancel_futures=False)
        if self.reader.is_alive() or self.processor.is_alive() or stats['unprocessed_tail_bytes'] or stats['unpersisted_tail_bytes']:
            raise DynamicError('rpc_spool_tail_incomplete','Required RPC tail has not completed',evidence=stats)
        self.rpc_spool.close()
        self.stderr_file.close()
        self.closed=True
