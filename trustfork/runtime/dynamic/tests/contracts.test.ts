import test from 'node:test';
import assert from 'node:assert/strict';
import {assertBridgeEnvelope} from '../contracts.ts';

test('shared Python/TS RPC contract rejects unknown fields, actors and epochs',()=>{
  const good={rpc_id:'rpc',actor_id:'C',opaque_session_id:'session',request_id:'request',branch_id:'branch',
    task_id:'task',stage_id:'stage',stage_epoch:0,invocation_id:null,operation:'execute_turn',payload:{}};
  assert.doesNotThrow(()=>assertBridgeEnvelope(good));
  for(const bad of [{...good,private_extra:'leak'},{...good,actor_id:'Attacker'},
    {...good,stage_epoch:-1},{...good,stage_epoch:0.5},{...good,payload:[]}])assert.throws(()=>assertBridgeEnvelope(bad));
  const missing:any={...good};delete missing.request_id;assert.throws(()=>assertBridgeEnvelope(missing));
});
