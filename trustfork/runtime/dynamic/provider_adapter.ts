/** Pi 0.84.1 owns conversion, stream parsing and tool calls. Only HTTP is relayed. */
import {stream, type OpenAICompletionsOptions} from '@earendil-works/pi-ai/api/openai-completions';
import type {Model,Context,OpenAICompletionsCompat} from '@earendil-works/pi-ai';

export type ProviderBinding={provider:string;base_url:string;model_id:string;
  context_window:number;max_output_tokens:number;supported_parameters:string[];thinking?:'enabled'|'disabled'|null;reasoning_effort?:'high'|null;
  api:'openai-completions';compat:OpenAICompletionsCompat;output_token_parameter:'max_tokens'|'max_completion_tokens'};
export type HttpReply={status:number;headers:Record<string,string>;body:string;read_error?:boolean};
export type Relay=(value:{url:string;method:string;body:string})=>Promise<HttpReply>;

export function providerModel(binding:ProviderBinding):Model<'openai-completions'>{
  for(const key of ['provider','base_url','model_id','context_window','max_output_tokens','api','compat','output_token_parameter'] as const)
    if(binding[key]===undefined || binding[key]===null || binding[key]==='')throw Error('Unresolved provider field: '+key);
  if(binding.api!=='openai-completions')throw Error('Unimplemented provider API; no fallback');
  for(const key of ['supportsStore','supportsDeveloperRole','supportsReasoningEffort','supportsUsageInStreaming',
    'supportsFinishReason','requiresToolResultName','requiresAssistantAfterToolResult','requiresThinkingAsText',
    'requiresReasoningContentOnAssistantMessages','supportsStrictMode'] as const)
    if(typeof binding.compat[key]!=='boolean')throw Error('Unresolved route compatibility: '+key);
  if((binding.thinking!=='enabled'&&!binding.supported_parameters.includes('temperature')) || !binding.supported_parameters.includes(binding.output_token_parameter))
    throw Error('Route must explicitly support planned temperature and output token parameter');
  return {id:binding.model_id,name:binding.model_id,api:binding.api,provider:binding.provider,baseUrl:binding.base_url,
    reasoning:binding.thinking==='enabled'||binding.thinking==='disabled',input:['text','image'],contextWindow:binding.context_window,maxTokens:binding.max_output_tokens,
    // Unknown prices are recorded as null by the host; this SDK placeholder is never used for billing.
    cost:{input:0,output:0,cacheRead:0,cacheWrite:0},compat:{...binding.compat,...(binding.thinking?{thinkingFormat:'deepseek' as const}:{}),maxTokensField:binding.output_token_parameter}};
}

export function providerStream(binding:ProviderBinding,context:Context,maxTokens:number,relay:Relay,
  onPayload:(payload:unknown)=>void,signal?:AbortSignal,onWireError?:(error:any)=>void){
  const model=providerModel(binding);
  if(maxTokens>binding.max_output_tokens)throw Error('Output budget exceeds bound route');
  const fetch:NonNullable<OpenAICompletionsOptions['fetch']>=async(input,init)=>{
    const request=new Request(input as RequestInfo,init);
    // Never forward SDK headers, credentials, environment or redirects over RPC.
    let reply:HttpReply;
    try{
      reply=await relay({url:request.url,method:request.method,body:await request.text()});
      validateToolArgumentJson(reply);
    }catch(error){onWireError?.(error);throw error;}
    const body=reply.read_error?new ReadableStream<Uint8Array>({start(controller){
      controller.enqueue(new TextEncoder().encode(reply.body));
      setTimeout(()=>controller.error(Error('Provider stream interrupted; partial generation retained')),0);
    }}):reply.body;
    return new Response(body,{status:reply.status,headers:reply.headers});
  };
  return stream(model,context,{apiKey:'host-relay-placeholder',
    ...(binding.thinking==='enabled'?{reasoningEffort:binding.reasoning_effort??'high'}:{temperature:0.2}),maxTokens,maxRetries:0,
    cacheRetention:'none',signal,fetch,onPayload:(payload)=>{
      const p=payload as any;
      if(binding.thinking){
        const enabled=binding.thinking==='enabled';
        if(p.thinking?.type!==binding.thinking || (enabled&&p.reasoning_effort!==binding.reasoning_effort))
          throw Error('Pi did not emit bound DeepSeek thinking mode/effort');
        if(enabled && 'temperature' in p)throw Error('Thinking temperature must not claim sampling effect');
        const expected=context.messages.filter(m=>m.role==='assistant'&&m.content.some(b=>b.type==='thinking'&&b.thinking.length))
          .map(m=>(m.content as any[]).filter(b=>b.type==='thinking'&&b.thinking.trim()).map(b=>b.thinking).join('\n'));
        const replay=p.messages.filter((m:any)=>m.role==='assistant'&&m.reasoning_content).map((m:any)=>m.reasoning_content);
        if(enabled&&JSON.stringify(expected)!==JSON.stringify(replay))throw Error('Incomplete private reasoning replay');
      }else if('thinking' in p || 'reasoning_effort' in p)throw Error('GPT route received DeepSeek-only parameters');
      onPayload(payload);return undefined;
    }});
}

// Pi's partial JSON parser must never turn an unfinished JSON string into a work operation.
export function validateToolArgumentJson(reply:HttpReply){
  if(reply.status!==200 || !reply.headers['content-type']?.startsWith('text/event-stream'))return;
  const args=new Map<string,string>();
  for(const line of reply.body.split(/\r?\n/)){
    if(!line.startsWith('data: ')||line.slice(6)==='[DONE]')continue;
    let data:any;try{data=JSON.parse(line.slice(6));}catch{continue;}
    for(const choice of data.choices??[])for(const call of choice.delta?.tool_calls??[]){
      const id=String(choice.index??0)+':'+String(call.index??0);
      if(call.function?.arguments!==undefined)args.set(id,(args.get(id)??'')+call.function.arguments);
    }
  }
  for(const value of args.values()){
    try{JSON.parse(value);}catch{throw Object.assign(Error('Incomplete raw tool argument JSON; retained reply is not executable'),{code:'provider_tool_json_incomplete'});}
  }
}
