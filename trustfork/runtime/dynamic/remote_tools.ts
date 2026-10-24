/** Pi owns argument validation, matching, editing, truncation and tool errors. */
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { readFile, unlink } from 'node:fs/promises';
import path from 'node:path';
import { AsyncLocalStorage } from 'node:async_hooks';
import {
  createReadToolDefinition, createBashToolDefinition, createEditToolDefinition,
  createWriteToolDefinition, createGrepToolDefinition, createFindToolDefinition,
  createLsToolDefinition, type ToolDefinition, type GrepOperations, type FindOperations,
} from '@earendil-works/pi-coding-agent';

export type Frame = {kind: 'data'; stream: 'stdout'|'stderr'; data: string} |
  {kind:'exit'; result:{exitCode:number|null; timed_out:boolean}};
export interface RemoteTransport {
  home: string;
  request(operation: string, args: Record<string, unknown>, opId: string): Promise<any>;
  stream(args: Record<string, unknown>, opId: string, onFrame: (frame: Frame)=>void): Promise<void>;
  cancel(opId: string): Promise<void>;
}
export const workIoContext = new AsyncLocalStorage<boolean>();

class RemoteChild extends EventEmitter {
  stdout = new PassThrough();
  stderr = new PassThrough();
  killed = false;
  readonly transport:RemoteTransport;
  readonly args:string[];
  readonly opId:string;
  readonly executable:string;
  constructor(transport:RemoteTransport, args:string[], opId:string, executable='rg') {
    super();
    this.transport=transport; this.args=args; this.opId=opId;this.executable=executable;
    queueMicrotask(() => { void this.start(); });
  }
  kill(): boolean {
    if (this.killed) return false;
    this.killed = true;
    void this.transport.cancel(this.opId).catch(error => this.emit('error', error));
    return true;
  }
  async start() {
    let exit: number|null = null;
    try {
      await this.transport.stream({argv:[this.executable, ...this.args], cwd:'/workspace'}, this.opId, frame => {
        if (frame.kind === 'data') this[frame.stream].write(Buffer.from(frame.data,'base64'));
        else exit = frame.result.exitCode;
      });
      this.stdout.end(); this.stderr.end();
      this.emit('close', exit);
    } catch (error) {
      this.stdout.end(); this.stderr.end(); this.emit('error', error);
    }
  }
}

function taskPath(input: string, home: string): string {
  const value = input.startsWith('@') ? input.slice(1) : input;
  if (value === '~') return home;
  return value.startsWith('~/') ? path.posix.join(home,value.slice(2)) : value;
}

export function createRemoteTools(transport: RemoteTransport, spoolRoot:string): ToolDefinition<any,any,any>[] {
  let serial = 0;
  const callContext = new AsyncLocalStorage<string>();
  const id = () => {
    const call = callContext.getStore();
    if (!call) throw Error('Remote IO has no actual Pi tool call');
    return (call + '-' + ++serial).replace(/[^A-Za-z0-9_-]/g,'_');
  };
  const request = (op:string, args:Record<string,unknown>) => transport.request(op,args,id());
  const read = async (p:string):Promise<Buffer> => Buffer.from((await request('fs.read',{path:p})).data,'base64');
  const access = async (p:string, mode=4) => {await request('fs.access',{path:p,mode});};
  const write = async (p:string, data:string|Buffer) => {await request('fs.write',{path:p,data:Buffer.from(data).toString('base64')});};
  const exists = async (p:string) => (await request('fs.exists',{path:p})).exists as boolean;
  const mkdir = async (p:string) => {await request('fs.mkdir',{path:p});};
  const realpath = async (p:string):Promise<string> => (await request('fs.realpath',{path:p})).path;
  const grepOps: GrepOperations = {
    isDirectory: async p => (await request('fs.stat',{path:p})).isDirectory,
    readFile: async p => (await read(p)).toString('utf8'),
    spawn: args => new RemoteChild(transport,args,id()) as unknown as ReturnType<NonNullable<GrepOperations['spawn']>>,
  };
  if (typeof grepOps.spawn !== 'function') throw Error('Grep requires the locked remote spawn callback');
  const findOps:FindOperations={exists,
    spawn:args=>new RemoteChild(transport,args,id(),'/usr/local/bin/fd') as unknown as ReturnType<NonNullable<FindOperations['spawn']>>};
  const bash = createBashToolDefinition('/workspace', {exposeSessionEnvironment:false, operations:{
    exec: async (command,cwd,{onData,signal,timeout}) => {
      const opId=id(); let result:{exitCode:number|null; timed_out:boolean}|undefined;
      const abort=()=>{void transport.cancel(opId);};
      if (signal?.aborted) throw Error('aborted');
      signal?.addEventListener('abort',abort,{once:true});
      try {
        await transport.stream({command,cwd,...(timeout===undefined?{}:{timeout})},opId,frame=>{
          if(frame.kind==='data') onData(Buffer.from(frame.data,'base64')); else result=frame.result;
        });
        if (signal?.aborted) throw Error('aborted');
        if (!result) throw Error('Remote command has no terminal frame');
        if (result.timed_out) throw Error(`timeout:${timeout}`);
        return {exitCode:result.exitCode};
      } finally { signal?.removeEventListener('abort',abort); }
    },
  }});
  const originalBash = bash.execute.bind(bash);
  bash.execute = async (callId,args,signal,_onUpdate,ctx) => {
    // Pi's unchanged OutputAccumulator creates a control-side transcript spool.
    // Move its public full-output reference into the task before any result is
    // returned. Neither model-facing paths nor future reads point to the host.
    const result = await originalBash(callId,args,signal,undefined,ctx);
    const source = result.details?.fullOutputPath;
    if (source) {
      const basename = path.basename(source);
      if (path.dirname(source)!==path.resolve(spoolRoot) || !/^pi-bash-[a-f0-9]{16}\.log$/.test(basename)) throw Error('Unexpected SDK spool path');
      const target = '/tmp/' + basename;
      await write(target, await readFile(source));
      result.details!.fullOutputPath = target;
      for(const item of result.content) if(item.type==='text') item.text=item.text.replaceAll(source,target);
      await unlink(source);
    }
    return result;
  };
  const definitions:ToolDefinition<any,any,any>[] = [
    createReadToolDefinition('/workspace',{operations:{readFile:read,access,
      detectImageMimeType: async p => {
        // Pure byte detector from the fixed SDK; its file-reading helper is not used.
        const utility = await import('./node_modules/@earendil-works/pi-coding-agent/dist/utils/mime.js');
        return utility.detectSupportedImageMimeType((await read(p)).subarray(0,4100));
      }}}),
    bash,
    createEditToolDefinition('/workspace',{operations:{readFile:read,writeFile:write,access,realpath}}),
    createWriteToolDefinition('/workspace',{operations:{writeFile:write,mkdir,realpath}}),
    createGrepToolDefinition('/workspace',{operations:grepOps}),
    createFindToolDefinition('/workspace',{operations:findOps}),
    createLsToolDefinition('/workspace',{operations:{exists,
      stat:async p=>{const stat=await request('fs.stat',{path:p});return{isDirectory:()=>stat.isDirectory};},
      readdir:async p=>(await request('fs.readdir',{path:p})).entries}}),
  ];
  for (const definition of definitions) {
    const original = definition.execute.bind(definition);
    definition.execute = (callId,args,signal,onUpdate,ctx) => callContext.run(callId,()=>workIoContext.run(true,()=>{
      const mapped={...(args as Record<string,unknown>)};
      if (typeof mapped.path==='string') mapped.path=taskPath(mapped.path,transport.home);
      return original(callId,mapped,signal,onUpdate,ctx);
    }));
  }
  if (new Set(definitions.map(x=>x.name)).size!==7) throw Error('Incomplete remote tool registry');
  return definitions;
}
