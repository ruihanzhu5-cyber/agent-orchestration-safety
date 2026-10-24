"""Continuously dispatch Pi RPC while each actor's one-turn call is pending."""
from __future__ import annotations
import concurrent.futures
import errno
import copy
import json
import os
import subprocess
import threading
import uuid
from pathlib import Path

from .common import DynamicError, canonical, digest
from .schema import validate_contract


class PiClient:
    def __init__(self, root, environment, *, ledger=None, coordination=None, observer=None):
        self.root, self.environment = Path(root).resolve(), environment
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger, self.coordination = ledger, coordination
        self.observer=observer
        runtime = Path(__file__).parent
        node = Path(os.environ.get('TRUSTFORK_NODE_BIN', str(Path.home()/'.local/share/trustfork-env/node-v24.15.0-linux-x64/bin/node')))
        if not node.is_file():
            raise DynamicError('missing_locked_node', 'Set TRUSTFORK_NODE_BIN to audited Linux Node 24.15.0')
        self.pending, self.scopes, self.sessions, self.actual_inputs = {}, {}, {}, {}
        self.lock, self.write_lock = threading.RLock(), threading.RLock()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=12, thread_name_prefix='pi-rpc')
        self.stderr_file = (self.root/'bridge.stderr.log').open('w')
        spool = self.root/'spool'
        spool.mkdir(exist_ok=True)
        self.process = subprocess.Popen([str(node), str(runtime/'pi_bridge.ts')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr_file, text=True, bufsize=1, cwd=runtime,
            env={'PATH':str(node.parent)+':/usr/bin:/bin', 'LANG':'C.UTF-8', 'TMPDIR':str(spool), 'PI_OFFLINE':'1'})
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.closed = False
        self.cleanup_errors=[]

    def _write(self, row):
        with self.write_lock:
            if self.process.poll() is not None:
                raise DynamicError('bridge_exited', str(self.process.returncode))
            self.process.stdin.write(canonical(row).decode()+'\n')
            self.process.stdin.flush()

    def _read(self):
        try:
            for line in self.process.stdout:
                row = json.loads(line)
                if row.get('kind') == 'result':
                    with self.lock:
                        future = self.pending.pop(row['rpc_id'], None)
                        self.scopes.pop(row['rpc_id'], None)
                    if future is None:
                        raise DynamicError('unknown_bridge_result', row['rpc_id'])
                    if row.get('error'):
                        future.set_exception(DynamicError('pi_bridge_error', row['error']))
                    else:
                        future.set_result(row['payload'])
                elif row.get('kind') == 'event':
                    if row.get('operation') in ('model_request_submitted','pi_event'):
                        self._handle_event(row)
                    else:
                        self.executor.submit(self._handle_event, row)
                else:
                    raise DynamicError('invalid_bridge_frame', str(row.get('kind')))
        except (OSError, ValueError, DynamicError) as error:
            self._fail_pending(error)
        finally:
            self._fail_pending(DynamicError('bridge_transport_closed', 'Pi transport closed before a response'))

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
            if operation in ('model_request_submitted','pi_event'):
                if operation=='model_request_submitted':self.actual_inputs[row['request_id']] = copy.deepcopy(payload['actual_input'])
                if self.ledger:
                    self.ledger.append(operation, payload, actor_id=row['actor_id'], stage_id=row['stage_id'],
                        stage_epoch=row['stage_epoch'], request_id=row['request_id'], invocation_id=row['invocation_id'])
                return
            identity = 'op_' + digest({'session':row['opaque_session_id'],'request':row['request_id'],'op':payload.get('op_id')})
            scope={k:row[k] for k in ('actor_id','stage_id','stage_epoch','request_id','invocation_id')}
            if operation == 'tool_operation':
                result = self.environment.exec_work_operation(payload['operation'],payload['args'],identity,scope=scope)
            elif operation == 'tool_stream':
                for frame in self.environment.stream_work_operation(payload['args'],identity,scope=scope):
                    self._write({'kind':'host_response','rpc_id':row['rpc_id'],'frame':frame})
                result = {'status':'complete'}
            elif operation == 'tool_cancel':
                result = self.environment.cancel_operation(identity)
            elif operation == 'coordination_tool':
                if self.coordination is None:
                    raise DynamicError('missing_coordination_handler', payload['name'])
                result = self.coordination(row['actor_id'],payload['name'],payload['args'],row)
            else:
                raise DynamicError('unknown_bridge_event', operation)
            if self.observer and operation in ('tool_operation','tool_stream'):
                actual_op=payload.get('operation','process.stream')
                if actual_op in ('fs.write','process.bash','process.argv','process.stream'):
                    self.observer(row,identity,actual_op,payload['args'])
            self._write({'kind':'host_response','rpc_id':row['rpc_id'],'payload':result})
        except (OSError, ValueError, DynamicError, subprocess.SubprocessError) as error:
            if row['operation'] in ('model_request_submitted','pi_event'):
                self._fail_pending(error)
            else:
                number = error.evidence.get('errno') if isinstance(error,DynamicError) and isinstance(error.evidence,dict) else None
                self._write({'kind':'host_response','rpc_id':row['rpc_id'],
                    'error':{'message':str(error),'code':errno.errorcode.get(number) if number else None}})

    def call(self, session_id, operation, payload=None, *, request_id=None, stage_id='initial', epoch=0, invocation_id=None, timeout=180):
        config = self.sessions[session_id]
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
                    'request_id':request_id,'guard':result['guard'],'mode':'scripted-test'})+b'\n')
            if any(result['guard'][k] for k in ('network_attempts','blocked_host_fs','blocked_host_exec')):
                raise DynamicError('isolation_trap_failed', 'A host task IO or network attempt was trapped', evidence=result['guard'])
        if operation=='close':self.sessions.pop(session_id,None)
        return result

    def create_session(self, actor_id, *, branch_id, task_id, system_prompt, task_resources=None, task_home='/root', snapshot=None):
        identity = uuid.uuid4().hex
        self.sessions[identity]={'actor_id':actor_id,'branch_id':branch_id,'task_id':task_id}
        payload = {'mode':'scripted-test','system_prompt':system_prompt,'task_resources':task_resources or [],
                   'task_home':task_home,'control_dir':str(self.root/'sessions'/identity)}
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
        self.executor.shutdown(wait=True,cancel_futures=False)
        self.stderr_file.close()
        self.closed=True
