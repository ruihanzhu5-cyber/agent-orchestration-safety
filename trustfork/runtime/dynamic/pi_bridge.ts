/** Passive JSONL worker: no ready queue, one real Pi core turn per permit. */
import {createInterface} from 'node:readline';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {Type} from 'typebox';
import {createAssistantMessageEventStream, type AssistantMessage, type Model} from '@earendil-works/pi-ai';
import {
  createAgentSession, SessionManager, SettingsManager, ModelRuntime, createExtensionRuntime,
  createSyntheticSourceInfo, parseFrontmatter,
  type AgentSession, type ResourceLoader, type ToolDefinition, type Skill,
} from '@earendil-works/pi-coding-agent';
import {createRemoteTools, type RemoteTransport, type Frame} from './remote_tools.ts';
import {installGuards} from './io_guard.ts';
import {assertBridgeEnvelope} from './contracts.ts';
import {providerModel,providerStream} from './provider_adapter.ts';

export type Envelope={rpc_id:string;actor_id:string;opaque_session_id:string;request_id:string|null;
  branch_id:string;task_id:string;stage_id:string;stage_epoch:number;invocation_id:string|null;operation:string;payload:any};
const root=path.dirname(fileURLToPath(import.meta.url));
const sdkRoot=path.join(root,'node_modules/@earendil-works/pi-coding-agent');
const patchLock=JSON.parse(await readFile(path.join(root,'pi-patch.lock.json'),'utf8'));
if(JSON.parse(await readFile(path.join(sdkRoot,'package.json'),'utf8')).version!==patchLock.pi_version || patchLock.pi_version!=='0.84.1')throw Error('Pi version lock failed');
for(const item of patchLock.files)if(createHash('sha256').update(await readFile(path.join(sdkRoot,item.path))).digest('hex')!==item.patched_sha256)throw Error('Pi patched-file hash lock failed: '+item.path);
const spoolRoot=process.env.TMPDIR;
if(!spoolRoot || !path.isAbsolute(spoolRoot)) throw Error('An isolated absolute TMPDIR is required');
await mkdir(spoolRoot,{recursive:true});
const guard=installGuards(spoolRoot,path.join(root,'node_modules'));
const send=(row:unknown)=>{process.stdout.write(JSON.stringify(row)+'\n');};
const pending=new Map<string,{resolve:(value:any)=>void;reject:(error:Error)=>void;onFrame?:(frame:Frame)=>void}>();
function callHost(envelope:Envelope,operation:string,payload:any,onFrame?:(frame:Frame)=>void):Promise<any>{
  const rpc_id=randomUUID();
  return new Promise((resolve,reject)=>{pending.set(rpc_id,{resolve,reject,onFrame});send({...envelope,rpc_id,operation,payload,kind:'event'});});
}
const scriptedModel:Model<'openai-completions'>={id:'synthetic-offline',name:'Scripted offline fixture',
  api:'openai-completions',provider:'scripted',baseUrl:'http://invalid.invalid',reasoning:false,input:['text','image'],
  cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:128000,maxTokens:4096};
type Script={text?:string;tools?:Array<{id:string;name:string;arguments:Record<string,unknown>}>;
  stopReason?:'stop'|'toolUse'|'error'|'aborted'|'length';errorMessage?:string;outputTokens?:number;
  transportFailure?:'http_429'|'disconnect_before_generation';delayMs?:number};
class TaskResources implements ResourceLoader {
  resources:Array<{path:string;content:string;kind?:string}>; basePrompt:string;
  extensions={extensions:[],errors:[],runtime:createExtensionRuntime()};
  constructor(resources:Array<{path:string;content:string}>,prompt:string){this.resources=resources;this.basePrompt=prompt;}
  getExtensions(){return this.extensions;}
  getSkills(){
    const skills:Skill[]=this.resources.filter(x=>x.kind==='skill').map(x=>{
      const {frontmatter}=parseFrontmatter<Record<string,unknown>>(x.content);
      if(typeof frontmatter.description!=='string')throw Error('Original task skill has no description: '+x.path);
      return {name:typeof frontmatter.name==='string'?frontmatter.name:path.basename(path.dirname(x.path)),
        description:frontmatter.description,filePath:x.path,baseDir:path.dirname(x.path),
        sourceInfo:createSyntheticSourceInfo(x.path,{source:'original-task',scope:'project',origin:'top-level',baseDir:path.dirname(x.path)}),
        disableModelInvocation:frontmatter['disable-model-invocation']===true};
    });
    return {skills,diagnostics:[]};
  }
  getPrompts(){return {prompts:[],diagnostics:[]};}
  getThemes(){return {themes:[],diagnostics:[]};}
  getAgentsFiles(){return {agentsFiles:this.resources.filter(x=>x.kind!=='skill').map(({path,content})=>({path,content}))};}
  getSystemPrompt(){return this.basePrompt;}
  getSystemPromptSource(){return undefined;}
  getAppendSystemPrompt(){return [];}
  getAppendSystemPromptSources(){return [];}
  extendResources(){throw Error('Unreviewed extension resources are disabled in dynamic mode');}
  async reload(){} // Sources are explicitly re-supplied and versioned by the host.
}
type OwnedSession={session:AgentSession;manager:SessionManager;resources:TaskResources;config:any;active:Envelope|null;
  scripts:Script[];requests:number;actualInputs:any[];events:any[];transport:RemoteTransport;lastResponse:AssistantMessage|null;abortRequested:boolean;providerError:any};
const sessions=new Map<string,OwnedSession>();
function requireSession(e:Envelope){
  const s=sessions.get(e.opaque_session_id);
  if(!s || s.config.actor_id!==e.actor_id || s.config.branch_id!==e.branch_id || s.config.task_id!==e.task_id) throw Error('Unknown or cross-scope session');
  return s;
}
function coordinateDefinitions(owned:()=>OwnedSession):ToolDefinition<any,any,any>[] {
  const definitions=[
    ['send_message',Type.Object({recipients:Type.Array(Type.String()),content:Type.String(),parent_id:Type.Optional(Type.String())})],
    ['get_team_directory',Type.Object({})],
    ['deliver_work',Type.Object({recipients:Type.Array(Type.String()),content:Type.String(),
      forward_of:Type.Optional(Type.String()),complete_invocation:Type.Optional(Type.Boolean())})],
    ['get_public_profile',Type.Object({agent_id:Type.String(),view:Type.Optional(Type.Union([Type.Literal('summary'),Type.Literal('records'),Type.Literal('full')]))})],
    ['get_profile_record',Type.Object({evidence_ref:Type.String()})],['get_work_sample',Type.Object({work_sample_ref:Type.String()})],
    ['get_profile_statistics',Type.Object({agent_id:Type.String(),kind:Type.Union([Type.Literal('family'),Type.Literal('recent')])})],
    ['get_historical_config',Type.Object({historical_config_id:Type.String()})],
    ['delegate_work',Type.Object({actor_id:Type.String(),task_text:Type.String()})],
    ['update_delegation',Type.Object({delegation_id:Type.String(),task_text:Type.String()})],
    ['cancel_delegation',Type.Object({delegation_id:Type.String()})],
    ['recruit',Type.Object({actor_ids:Type.Array(Type.String())})],['release_member',Type.Object({actor_id:Type.String()})],
  ] as const;
  return definitions.filter(([name])=>owned().config.actor_id==='Main' || !['delegate_work','update_delegation','cancel_delegation','recruit','release_member'].includes(name)).map(([name,parameters])=>({
    name,label:name,description:'Team coordination: '+name,parameters,
    execute:async(callId:string,args:any)=>{
      const s=owned();if(!s.active) throw Error('No actor permit');
      const result=await callHost(s.active,'coordination_tool',{name,args,tool_call_id:callId});
      return {content:[{type:'text' as const,text:JSON.stringify(result)}],details:undefined};
    },
  }));
}
async function create(e:Envelope,restore?:any){
  if(sessions.has(e.opaque_session_id)) throw Error('Session already exists');
  if(!['scripted-test','mock','api'].includes(e.payload.mode)) throw Error('Explicit execution backend required');
  if(e.payload.mode!=='scripted-test'&&!e.payload.provider_binding)throw Error('Missing exact provider binding');
  const directory=path.resolve(e.payload.control_dir);
  await mkdir(directory,{recursive:true});await writeFile(path.join(directory,'auth.json'),'{}\n');
  const resources=new TaskResources(e.payload.task_resources??[],e.payload.system_prompt);
  let manager:SessionManager;
  if(restore){
    const filename=path.join(directory,'restored-session.jsonl');
    await writeFile(filename,[restore.header,...restore.entries].map(x=>JSON.stringify(x)).join('\n')+'\n');
    manager=SessionManager.open(filename,path.join(directory,'sessions'),'/workspace');
    if(restore.leaf_id)manager.branch(restore.leaf_id);else manager.resetLeaf();
  }else manager=SessionManager.create('/workspace',path.join(directory,'sessions'));
  const settings=SettingsManager.inMemory({retry:{enabled:false,maxRetries:0,provider:{maxRetries:0}},
    compaction:{enabled:false},enableAnalytics:false,enableInstallTelemetry:false,packages:[],extensions:[],skills:[],prompts:[],themes:[]});
  const runtime=await ModelRuntime.create({authPath:path.join(directory,'auth.json'),modelsPath:null,
    modelsStorePath:path.join(directory,'models-cache.json'),allowModelNetwork:false,refreshOnCreate:false});
  let s:OwnedSession;
  const transport:RemoteTransport={home:e.payload.task_home??'/root',
    observe:async record=>{if(!s.active)throw Error('No tool visibility scope');
      send({...s.active,kind:'event',rpc_id:randomUUID(),operation:'tool_visibility',payload:record});},
    request:async(operation,args,opId)=>{if(!s.active)throw Error('No tool permit');return callHost(s.active,'tool_operation',{operation,args,op_id:opId});},
    stream:async(args,opId,onFrame)=>{if(!s.active)throw Error('No stream permit');await callHost(s.active,'tool_stream',{args,op_id:opId},onFrame);},
    cancel:async(opId)=>{if(!s.active)throw Error('No cancellation scope');await callHost(s.active,'tool_cancel',{op_id:opId});},
  };
  const work=e.actor_id==='Main'?[]:createRemoteTools(transport,spoolRoot!);
  const config={...e.payload,actor_id:e.actor_id,branch_id:e.branch_id,task_id:e.task_id};
  s={session:undefined as unknown as AgentSession,manager,resources,config,active:null,scripts:[],requests:0,actualInputs:[],events:[],transport,lastResponse:null,abortRequested:false,providerError:null};
  const tools=[...work,...coordinateDefinitions(()=>s)];
  const model=e.payload.mode==='scripted-test'?scriptedModel:providerModel(e.payload.provider_binding);
  const created=await createAgentSession({cwd:'/workspace',agentDir:directory,modelRuntime:runtime,model,
    thinkingLevel:e.payload.provider_binding?.thinking==='enabled'?'high':'off',resourceLoader:resources,sessionManager:manager,settingsManager:settings,
    noTools:'builtin',tools:tools.map(x=>x.name),customTools:tools});
  if(created.modelFallbackMessage)throw Error('Unexpected model fallback');
  s.session=created.session;
  s.session.agent.shouldStopAfterTurn=()=>true;
  s.session.agent.getApiKey=()=>undefined;
  s.session.agent.streamFunction=(_model,context,options)=>{
    const stream=createAssistantMessageEventStream();
    const active=s.active;
    if(!active)throw Error('Pi attempted generation without host permit');
    s.requests++;
    const actual={systemPrompt:context.systemPrompt,messages:context.messages,
      tools:(context.tools??[]).map(t=>({name:t.name,description:t.description,parameters:t.parameters})),
      provider_parameters:{maxRetries:0,maxTokens:active.payload.max_output_tokens??4096,
        ...(s.config.mode==='scripted-test'?{}:s.config.provider_binding.thinking==='enabled'?{thinking:'enabled',reasoning_effort:'high'}:{temperature:0.2})}};
    s.actualInputs.push(structuredClone(actual));
    send({...active,kind:'event',rpc_id:randomUUID(),operation:'model_request_submitted',payload:{actual_input:actual,synthetic:s.config.mode!=='api',execution_backend:s.config.mode}});
    if(s.config.mode!=='scripted-test')return providerStream(s.config.provider_binding,context,active.payload.max_output_tokens??4096,
      value=>callHost(active,'provider_http',value),payload=>send({...active,kind:'event',rpc_id:randomUUID(),
        operation:'provider_payload',payload:{request:payload,execution_backend:s.config.mode,synthetic:s.config.mode!=='api'}}),options?.signal,error=>{s.providerError={code:error.code??'provider_transport_unknown',message:String(error)};});
    const script=s.scripts.shift();
    const produce=()=>{
      const failure=!script;
      const content:AssistantMessage['content']=[...(script?.text===undefined?[]:[{type:'text' as const,text:script.text}]),
        ...(script?.tools??[]).map(x=>({type:'toolCall' as const,...x}))];
      const stopReason=failure||script?.transportFailure?'error':script.stopReason??((script.tools?.length??0)>0?'toolUse':'stop');
      const tokens=script?.outputTokens??Math.ceil(JSON.stringify(content).length/4);
      const message:AssistantMessage={role:'assistant',content,api:scriptedModel.api,provider:scriptedModel.provider,
        model:scriptedModel.id,timestamp:Date.now(),stopReason,errorMessage:failure?'Script exhausted':script?.errorMessage,
        usage:{input:0,output:tokens,cacheRead:0,cacheWrite:0,totalTokens:tokens,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}};
      if(stopReason==='error'||stopReason==='aborted') stream.push({type:'error',reason:stopReason,error:message});
      else stream.push({type:'done',reason:stopReason,message});
      stream.end(message);
    };
    if(script?.delayMs)setTimeout(produce,script.delayMs);else queueMicrotask(produce);
    return stream;
  };
  s.session.agent.subscribe(event=>{
    s.events.push(structuredClone(event));
    if(event.type==='message_end' && event.message.role==='assistant')s.lastResponse=event.message;
    if(s.active)send({...s.active,kind:'event',rpc_id:randomUUID(),operation:'pi_event',payload:{event}});
  });
  const actual=s.session.getActiveToolNames().sort();
  if(JSON.stringify(actual)!==JSON.stringify(tools.map(x=>x.name).sort()))throw Error('Final Pi registry differs from explicit remote definitions');
  if(e.actor_id==='Main' && actual.some(x=>['read','bash','edit','write','grep','find','ls'].includes(x)))throw Error('Main received work tools');
  if(restore?.active_tool_names){
    if(restore.active_tool_names.some((name:string)=>!actual.includes(name)))throw Error('Restored registry contains an unavailable tool');
    s.session.setActiveToolsByName(restore.active_tool_names);
  }
  sessions.set(e.opaque_session_id,s);
  return {status:'created',registry:actual,synthetic:s.config.mode!=='api',execution_backend:s.config.mode,pi_version:'0.84.1'};
}
async function dispatch(e:Envelope){
  if(e.operation==='create_session')return create(e);
  if(e.operation==='restore_session')return create(e,e.payload.snapshot);
  const s=requireSession(e);
  if(e.operation==='cancel'){s.abortRequested=!!s.active;s.session.agent.abort();return{status:'cancel_requested'};}
  if(e.operation==='execute_turn'){
    if(s.active)throw Error('Actor already has an active permit');
    s.active=e;s.scripts=[e.payload.script];s.lastResponse=null;s.abortRequested=false;s.providerError=null;
    const before=s.requests,start=s.events.length;
    try{
      if(e.payload.messages?.length) await s.session.agent.prompt(e.payload.messages);
      else{
        const last=s.session.agent.state.messages.at(-1);
        if(!last || !['user','toolResult'].includes(last.role))return{status:'idle',requests:0};
        await s.session.agent.continue();
      }
      if(s.requests-before!==1)throw Error('Pi did not stop after one complete turn');
      const response=s.lastResponse as AssistantMessage|null;
      const status=s.abortRequested || !response || ['error','aborted'].includes(response.stopReason)?'infra_error':'success';
      const transport=e.payload.script?.transportFailure;
      const generated=!!response?.content.length;
      const effects=s.events.slice(start).some(x=>x.type==='tool_execution_start');
      return {status,response,error:s.providerError,generation_finish_reason:response?.stopReason??null,
        completion_status:status!=='success'?'unavailable':response?.stopReason==='length'?'partial':'complete',
        termination_reason:response?.stopReason==='length'?'output_limit':null,
        termination_status:s.abortRequested?'cancelled':status==='success'?(response?.stopReason==='length'?'resource_ended':'completed'):'provider_error',events:s.events.slice(start),requests:s.requests-before,
        transport_failure:transport?{code:transport,generation_received:generated,tool_effects_started:effects}:null,
        actual_input:s.actualInputs.at(-1),entries:s.manager.getEntries(),leaf_id:s.manager.getLeafId(),
        registry:s.session.getActiveToolNames(),guard:{...guard.counters},synthetic:s.config.mode!=='api',execution_backend:s.config.mode};
    }finally{s.active=null;s.scripts=[];}
  }
  if(s.active)throw Error('Session maintenance requires an idle turn boundary');
  if(e.operation==='export_session')return{header:s.manager.getHeader(),entries:s.manager.getEntries(),leaf_id:s.manager.getLeafId(),
    config:s.config,empty:s.session.agent.state.messages.length===0,messages:s.session.agent.state.messages,
    active_tool_names:s.session.getActiveToolNames(),synthetic:s.config.mode!=='api'};
  if(e.operation==='set_coordination_phase'){
    if(e.actor_id!=='Main'||!['planning','collaboration','history'].includes(e.payload.phase))throw Error('Invalid coordination phase');
    const names=coordinateDefinitions(()=>s).map(x=>x.name);
    s.session.setActiveToolsByName(e.payload.phase==='planning'?names.filter(x=>['delegate_work','update_delegation','cancel_delegation'].includes(x)):
      e.payload.phase==='history'?names.filter(x=>!['recruit','release_member'].includes(x)&&!x.startsWith('get_public_profile')&&!['get_profile_record','get_work_sample','get_profile_statistics','get_historical_config'].includes(x)):names);
    return{status:'phase_set',registry:s.session.getActiveToolNames()};
  }
  if(e.operation==='reload_resources'){
    s.resources.resources=e.payload.task_resources;s.resources.basePrompt=e.payload.system_prompt;
    await s.session.reload();s.session.agent.shouldStopAfterTurn=()=>true;
    return{status:'reloaded',system_prompt:s.session.agent.state.systemPrompt};
  }
  if(e.operation==='maintenance_compact_fixture'){
    const first=e.payload.first_kept_entry_id;
    if(!s.manager.getEntry(first))throw Error('Compaction must reference an actual Pi entry');
    s.manager.appendCompaction(e.payload.summary,first,e.payload.tokens_before,{synthetic:true,maintenance_request_id:e.request_id});
    s.session.agent.state.messages=s.manager.buildSessionContext().messages;
    return{status:'synthetic_compaction_applied',entries:s.manager.getEntries(),system_prompt:s.session.agent.state.systemPrompt};
  }
  if(e.operation==='probe_tool'){
    const definition=createRemoteTools(s.transport,spoolRoot!).find(x=>x.name===e.payload.name);
    if(!definition || e.actor_id==='Main')throw Error('Probe requires an actual Sub work definition');
    s.active=e;
    try{return {status:'success',result:await definition.execute(e.payload.tool_call_id,e.payload.args,undefined,undefined,{} as any),guard:{...guard.counters}};}
    finally{s.active=null;}
  }
  if(e.operation==='close'){s.session.dispose();sessions.delete(e.opaque_session_id);return{status:'closed',guard:{...guard.counters}};}
  throw Error('Unknown bridge operation');
}
const lines=createInterface({input:process.stdin});
lines.on('line',line=>{
  let e:any;
  try{e=JSON.parse(line);}catch{send({kind:'fatal',error:'invalid JSONL'});return;}
  if(e.kind==='host_response'){
    const wait=pending.get(e.rpc_id);if(!wait){send({kind:'fatal',error:'unknown rpc response'});return;}
    if(e.frame){wait.onFrame?.(e.frame);return;}
    pending.delete(e.rpc_id);
    if(e.error)wait.reject(Object.assign(Error(typeof e.error==='string'?e.error:e.error.message),{code:e.error.code}));else wait.resolve(e.payload);
    return;
  }
  try{assertBridgeEnvelope(e);}catch(error){send({kind:'fatal',error:String(error)});return;}
  void dispatch(e).then(payload=>send({...e,kind:'result',payload}),error=>send({...e,kind:'result',error:{message:String(error),code:(error as any).code??'pi_bridge_error'},payload:null}));
});
lines.on('close',()=>{for(const s of sessions.values())s.session.dispose();});
