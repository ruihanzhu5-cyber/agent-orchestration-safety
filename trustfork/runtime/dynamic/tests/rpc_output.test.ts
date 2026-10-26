import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Writable} from 'node:stream';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {RpcOutput} from '../rpc_output.ts';

test('slow stdout preserves 120 turns of incremental text/thinking/tool argument frames through bounded disk FIFO',async()=>{
 const root=mkdtempSync(path.join(tmpdir(),'trustfork-rpc-test-'));const chunks:Buffer[]=[];
 const slow=new Writable({highWaterMark:64,write(chunk,encoding,callback){setTimeout(()=>{chunks.push(Buffer.from(chunk));callback();},1);}});
 const output=new RpcOutput(path.join(root,'frames'),slow,1024);const expected:any[]=[];
 try{
  for(let turn=0;turn<120;turn++)for(const kind of ['thinking_delta','text_delta','toolcall_delta'])for(let part=0;part<8;part++){
   const row={request_id:'r'+turn,kind,part,text:'🙂真实增量'.repeat(10)};expected.push(row);output.enqueue(row);
  }
  assert.ok(output.stats().pending_disk_bytes>0);await output.flush();
  assert.deepEqual(Buffer.concat(chunks).toString().trim().split('\n').map(x=>JSON.parse(x)),expected);
  const stats=output.stats();assert.equal(stats.persisted_bytes,stats.processed_bytes);assert.equal(stats.accepted_bytes,stats.persisted_bytes);assert.equal(stats.pending_disk_bytes,0);assert.equal(stats.max_output_buffer_bytes,1024);
  // Repeat after the drain/truncate boundary, including explicit cancellation/finalize frames.
  output.enqueue({kind:'cancelled',request_id:'r120'});output.enqueue({kind:'finalized',request_id:'r120'});await output.close();
  assert.equal(output.stats().frames,expected.length+2);
 }finally{await output.close();rmSync(root,{recursive:true,force:true});}
});
