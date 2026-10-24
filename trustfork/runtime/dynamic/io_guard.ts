/** Work IO traps prove task paths never fall back to host fs/process APIs. */
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import cp from 'node:child_process';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import path from 'node:path';
import {syncBuiltinESMExports} from 'node:module';
import {workIoContext} from './remote_tools.ts';

export function installGuards(spoolRoot:string, sdkRoot:string) {
  const counters={real_model_requests:0, real_judge_requests:0, network_attempts:0,
    blocked_host_fs:[] as string[], blocked_host_exec:[] as string[]};
  const patches:Array<()=>void>=[];
  function replace(object:any,key:string,wrapper:(original:any)=>any) {
    const original=object[key];
    if(typeof original!=='function') return;
    object[key]=wrapper(original); patches.push(()=>{object[key]=original;});
  }
  const allowed=(p:unknown)=>{
    if(typeof p!=='string' && !(p instanceof URL) && !Buffer.isBuffer(p)) return true; // file descriptors of controlled SDK streams
    const value=String(p);
    return (path.dirname(value)===path.resolve(spoolRoot) && /^pi-bash-[a-f0-9]{16}\.log$/.test(path.basename(value))) ||
      value.startsWith(path.resolve(sdkRoot)+'/');
  };
  for(const object of [fs,fsp]) for(const key of ['access','accessSync','stat','statSync','lstat','lstatSync','readFile','readFileSync','writeFile','writeFileSync','open','openSync','readdir','readdirSync','mkdir','mkdirSync','realpath','realpathSync','unlink','unlinkSync','createReadStream','createWriteStream']) {
    replace(object,key,original=>function(this:any,p:unknown,...args:unknown[]) {
      if(workIoContext.getStore() && !allowed(p)) {
        counters.blocked_host_fs.push(String(p)); throw Error('HOST_FS_TRAP: task IO attempted on host');
      }
      return original.call(this,p,...args);
    });
  }
  for(const key of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']) {
    replace(cp,key,original=>function(this:any,...args:unknown[]) {
      if(workIoContext.getStore()) { counters.blocked_host_exec.push(String(args[0])); throw Error('HOST_EXEC_TRAP'); }
      return original.apply(this,args);
    });
  }
  const deny=()=>{counters.network_attempts++;throw Error('OFFLINE_NETWORK_GUARD');};
  const oldFetch=globalThis.fetch; globalThis.fetch=async()=>deny(); patches.push(()=>{globalThis.fetch=oldFetch;});
  for(const [object,keys] of [[http,['request','get']],[https,['request','get']],[net,['connect','createConnection']],[tls,['connect']]] as const)
    for(const key of keys) replace(object,key,()=>deny);
  syncBuiltinESMExports();
  return {counters,restore:()=>{for(const undo of patches.reverse())undo();syncBuiltinESMExports();}};
}
