import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import {workIoContext} from '../remote_tools.ts';
import {installGuards} from '../io_guard.ts';

test('negative trap blocks local work and outbound requests before execution',async()=>{
  const spool=await fs.mkdtemp(path.join(os.tmpdir(),'tf-negative-'));
  const guard=installGuards(spool,path.resolve('node_modules'));
  try{
    await assert.rejects(async()=>workIoContext.run(true,()=>fs.readFile('/workspace/host-trap.txt')),/HOST_FS_TRAP/);
    assert.throws(()=>workIoContext.run(true,()=>cp.spawn('sh',['-c','exit 99'])),/HOST_EXEC_TRAP/);
    await assert.rejects(fetch('https://invalid.invalid/never-send'),/OFFLINE_NETWORK_GUARD/);
    assert.equal(guard.counters.network_attempts,1);
    assert.deepEqual(guard.counters.blocked_host_fs,['/workspace/host-trap.txt']);
    assert.deepEqual(guard.counters.blocked_host_exec,['sh']);
    assert.equal(guard.counters.real_model_requests,0);assert.equal(guard.counters.real_judge_requests,0);
  }finally{guard.restore();}
});
