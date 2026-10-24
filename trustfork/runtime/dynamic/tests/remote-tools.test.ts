import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createRemoteTools,type RemoteTransport,type Frame} from '../remote_tools.ts';
import {installGuards} from '../io_guard.ts';

test('real Pi factories preserve edit, read and write contracts through remote operations',async()=>{
  const spool=await mkdtemp(path.join(os.tmpdir(),'tf-contract-'));
  const files=new Map<string,string>();
  const calls:string[]=[];
  const transport:RemoteTransport={home:'/root',cancel:async()=>{},stream:async()=>{throw Error('unexpected stream');},
    request:async(op,args)=>{
      calls.push(op);
      const p=String(args.path);
      if(op==='fs.mkdir')return{};
      if(op==='fs.realpath'){if(!files.has(p))throw Object.assign(Error('not found'),{code:'ENOENT'});return{path:p};}
      if(op==='fs.write'){files.set(p,Buffer.from(String(args.data),'base64').toString());return{};}
      if(op==='fs.access'){if(!files.has(p))throw Error('not found');return{};}
      if(op==='fs.read'){if(!files.has(p))throw Error('not found');return{data:Buffer.from(files.get(p)!).toString('base64')};}
      throw Error('unknown op');
    }};
  const tools=createRemoteTools(transport,spool);
  const sdk=path.resolve('node_modules');const guard=installGuards(spool,sdk);
  const execute=async(name:string,args:any)=>tools.find(t=>t.name===name)!.execute(name,args,undefined,undefined,{} as any);
  try{
    await execute('write',{path:'/workspace/fixture.txt',content:'alpha\nbeta\n'});
    await execute('edit',{path:'/workspace/fixture.txt',edits:[{oldText:'beta',newText:'gamma'}]});
    const read=await execute('read',{path:'/workspace/fixture.txt',offset:2,limit:1});
    assert.equal(read.content[0].type,'text');
    assert.match((read.content[0] as any).text,/gamma/);
    await assert.rejects(execute('edit',{path:'/workspace/fixture.txt',edits:[{oldText:'absent',newText:'x'}]}));
    assert.deepEqual(guard.counters.blocked_host_fs,[]);
    assert.deepEqual(guard.counters.blocked_host_exec,[]);
    assert.equal(guard.counters.network_attempts,0);
    assert(calls.includes('fs.read')&&calls.includes('fs.write')&&calls.includes('fs.access'));
  }finally{guard.restore();}
});

test('original per-file mutation queue serializes aliases while independent files stay concurrent',async()=>{
  const spool=await mkdtemp(path.join(os.tmpdir(),'tf-queue-'));
  const starts:string[]=[];
  let unlock!:()=>void;
  const hold=new Promise<void>(resolve=>{unlock=resolve;});
  const transport:RemoteTransport={home:'/root',cancel:async()=>{},stream:async()=>{},request:async(op,args)=>{
    if(op==='fs.realpath')return{path:String(args.path).includes('independent')?'/workspace/independent':'/workspace/canonical'};
    if(op==='fs.mkdir')return{};
    if(op==='fs.write'){
      const text=Buffer.from(String(args.data),'base64').toString();starts.push(text);
      if(text==='first')await hold;
      return{};
    }
    throw Error('unexpected operation');
  }};
  const tool=createRemoteTools(transport,spool).find(x=>x.name==='write')!;
  const exec=(id:string,file:string,content:string)=>tool.execute(id,{path:file,content},undefined,undefined,{} as any);
  const first=exec('first','/workspace/alias','first');
  const second=exec('second','/workspace/canonical','second');
  const independent=exec('other','/workspace/independent','other');
  await independent;
  assert(starts.includes('first')&&starts.includes('other')&&!starts.includes('second'));
  unlock();await Promise.all([first,second]);
  assert.equal(starts.at(-1),'second');
});
