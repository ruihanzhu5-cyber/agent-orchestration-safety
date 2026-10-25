/** Pi 0.84.1 owns conversion, stream parsing and tool calls. Only HTTP is relayed. */
import {stream, type OpenAICompletionsOptions} from '@earendil-works/pi-ai/api/openai-completions';
import type {Model,Context,OpenAICompletionsCompat} from '@earendil-works/pi-ai';

export type ProviderBinding={provider:string;base_url:string;model_id:string;
  context_window:number;max_output_tokens:number;supported_parameters:string[];
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
  if(!binding.supported_parameters.includes('temperature') || !binding.supported_parameters.includes(binding.output_token_parameter))
    throw Error('Route must explicitly support planned temperature and output token parameter');
  return {id:binding.model_id,name:binding.model_id,api:binding.api,provider:binding.provider,baseUrl:binding.base_url,
    reasoning:false,input:['text','image'],contextWindow:binding.context_window,maxTokens:binding.max_output_tokens,
    // Unknown prices are recorded as null by the host; this SDK placeholder is never used for billing.
    cost:{input:0,output:0,cacheRead:0,cacheWrite:0},compat:{...binding.compat,maxTokensField:binding.output_token_parameter}};
}

export function providerStream(binding:ProviderBinding,context:Context,maxTokens:number,relay:Relay,
  onPayload:(payload:unknown)=>void,signal?:AbortSignal){
  const model=providerModel(binding);
  if(maxTokens>binding.max_output_tokens)throw Error('Output budget exceeds bound route');
  const fetch:NonNullable<OpenAICompletionsOptions['fetch']>=async(input,init)=>{
    const request=new Request(input as RequestInfo,init);
    // Never forward SDK headers, credentials, environment or redirects over RPC.
    const reply=await relay({url:request.url,method:request.method,body:await request.text()});
    const body=reply.read_error?new ReadableStream<Uint8Array>({start(controller){
      controller.enqueue(new TextEncoder().encode(reply.body));
      setTimeout(()=>controller.error(Error('Provider stream interrupted; partial generation retained')),0);
    }}):reply.body;
    return new Response(body,{status:reply.status,headers:reply.headers});
  };
  return stream(model,context,{apiKey:'host-relay-placeholder',temperature:0.2,maxTokens,maxRetries:0,
    cacheRetention:'none',signal,fetch,onPayload:(payload)=>{onPayload(payload);return undefined;}});
}
