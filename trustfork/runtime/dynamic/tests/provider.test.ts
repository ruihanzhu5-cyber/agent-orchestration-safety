import test from 'node:test';
import assert from 'node:assert/strict';
import {providerStream,providerModel,type ProviderBinding} from '../provider_adapter.ts';
const binding:ProviderBinding={provider:'synthetic-provider',base_url:'https://mock.invalid/v1',model_id:'exact-mock-model',
  context_window:128000,max_output_tokens:4096,supported_parameters:['temperature','max_tokens'],api:'openai-completions',
  output_token_parameter:'max_tokens',compat:{supportsStore:false,supportsDeveloperRole:false,supportsReasoningEffort:false,
    supportsUsageInStreaming:true,supportsFinishReason:true,requiresToolResultName:false,requiresAssistantAfterToolResult:false,
    requiresThinkingAsText:false,requiresReasoningContentOnAssistantMessages:false,supportsStrictMode:false}};
function sse(delta:unknown,finish='stop'){
  return 'data: '+JSON.stringify({id:'mock-r',choices:[{index:0,delta,finish_reason:null}]})+'\n\n'+
    'data: '+JSON.stringify({id:'mock-r',choices:[{index:0,delta:{},finish_reason:finish}],usage:{prompt_tokens:12,completion_tokens:3,total_tokens:15}})+'\n\n'+'data: [DONE]\n\n';
}
test('locked Pi provider converts exact input/parameters and returns usage without external fetch',async()=>{
  const payloads:any[]=[];let calls=0;
  const result=await providerStream(binding,{systemPrompt:'system',messages:[{role:'user',content:'complete task input',timestamp:1}]},100,
    async wire=>{calls++;const body=JSON.parse(wire.body);assert.equal(body.model,'exact-mock-model');
      assert.equal(body.temperature,.2);assert.equal(body.max_tokens,100);assert.equal(wire.url,'https://mock.invalid/v1/chat/completions');
      assert.ok(body.messages.some((m:any)=>m.content==='complete task input'));
      return {status:200,headers:{'content-type':'text/event-stream'},body:sse({content:'answer'})};},p=>payloads.push(p)).result();
  assert.equal(calls,1);assert.equal(payloads.length,1);assert.equal(result.stopReason,'stop');assert.equal(result.usage.output,3);
  assert.equal((result.content[0] as any).text,'answer');
});
test('tool calls parse through Pi and replay tool results without another scheduler',async()=>{
  const first=await providerStream(binding,{messages:[{role:'user',content:'read',timestamp:1}]},100,
    async()=>({status:200,headers:{'content-type':'text/event-stream'},body:sse({tool_calls:[{index:0,id:'tool-one',type:'function',function:{name:'read',arguments:'{"path":"/workspace/a"}'}}]},'tool_calls')}),()=>{}).result();
  assert.equal(first.stopReason,'toolUse');assert.equal((first.content[0] as any).arguments.path,'/workspace/a');
  await providerStream(binding,{messages:[{role:'user',content:'read',timestamp:1},first,
    {role:'toolResult',toolCallId:'tool-one',toolName:'read',content:[{type:'text',text:'remote bytes'}],isError:false,timestamp:2}]},100,
    async wire=>{assert.ok(JSON.parse(wire.body).messages.some((m:any)=>m.role==='tool'&&m.content==='remote bytes'));
      return {status:200,headers:{'content-type':'text/event-stream'},body:sse({content:'finished'})};},()=>{}).result();
});
test('429 is one attempt; no SDK retry or model fallback',async()=>{
  let calls=0;
  const result=await providerStream(binding,{messages:[{role:'user',content:'x',timestamp:1}]},10,
    async()=>{calls++;return {status:429,headers:{'content-type':'application/json'},body:'{"error":{"message":"rate limited"}}'};},()=>{}).result();
  assert.equal(calls,1);assert.equal(result.stopReason,'error');assert.equal(result.model,binding.model_id);
});
test('truncation and partial stream failures retain distinct stop reasons',async()=>{
  const limited=await providerStream(binding,{messages:[]},10,async()=>({status:200,headers:{'content-type':'text/event-stream'},body:sse({content:'partial'},'length')}),()=>{}).result();
  assert.equal(limited.stopReason,'length');
  const interrupted=await providerStream(binding,{messages:[]},10,async()=>({status:200,headers:{'content-type':'text/event-stream'},body:'data: '+JSON.stringify({choices:[{index:0,delta:{content:'started'},finish_reason:null}]})+'\n\n',read_error:true}),()=>{}).result();
  assert.equal(interrupted.stopReason,'error');
});
test('missing route compat/model never guesses or switches model',()=>{
  assert.throws(()=>providerModel({...binding,model_id:''}),/Unresolved/);
  assert.throws(()=>providerModel({...binding,compat:{}}),/compatibility/);
  assert.throws(()=>providerModel({...binding,supported_parameters:['max_tokens']}),/temperature/);
});

test('timeout and malformed tool JSON remain errors/validation inputs, never retries',async()=>{
  let calls=0;
  const timeout=await providerStream(binding,{messages:[]},10,async()=>{calls++;throw Error('Mock timeout');},()=>{}).result();
  assert.equal(calls,1);assert.equal(timeout.stopReason,'error');
  const tool=await providerStream(binding,{messages:[]},10,async()=>({status:200,headers:{'content-type':'text/event-stream'},
    body:sse({tool_calls:[{index:0,id:'invalid',type:'function',function:{name:'write',arguments:'{"path":'}}]},'tool_calls')}),()=>{}).result();
  assert.equal(tool.stopReason,'toolUse');assert.equal((tool.content[0] as any).arguments.content,undefined);
});
