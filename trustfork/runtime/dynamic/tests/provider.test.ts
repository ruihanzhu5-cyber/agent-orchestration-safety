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
  assert.equal(tool.stopReason,'error');assert.equal(tool.content.filter(x=>x.type==='toolCall').length,0);
});

test('DeepSeek high thinking survives serialized session-shaped messages and replays every assistant reasoning',async()=>{
  const deep:ProviderBinding={...binding,provider:'deepseek',model_id:'deepseek-flash',thinking:'enabled',reasoning_effort:'high',
    compat:{...binding.compat,supportsReasoningEffort:true,requiresReasoningContentOnAssistantMessages:true}};
  const first=await providerStream(deep,{messages:[{role:'user',content:'think and answer',timestamp:1}]},100,
    async wire=>{
      const p=JSON.parse(wire.body);assert.deepEqual(p.thinking,{type:'enabled'});assert.equal(p.reasoning_effort,'high');assert.ok(!('temperature' in p));
      return {status:200,headers:{'content-type':'text/event-stream'},body:sse({reasoning_content:'private first',content:'ordinary answer'})};
    },()=>{}).result();
  const saved=JSON.parse(JSON.stringify(first));
  const second=await providerStream(deep,{messages:[{role:'user',content:'think and answer',timestamp:1},saved,
    {role:'user',content:'now use tool',timestamp:2}]},100,async wire=>{
      assert.equal(JSON.parse(wire.body).messages.find((m:any)=>m.role==='assistant').reasoning_content,'private first');
      return {status:200,headers:{'content-type':'text/event-stream'},body:sse({reasoning_content:'private tool',
        tool_calls:[{index:0,id:'deep-tool',type:'function',function:{name:'read',arguments:'{"path":"/workspace/a"}'}}]},'tool_calls')};
    },()=>{}).result();
  assert.equal(second.stopReason,'toolUse');
  await providerStream(deep,{messages:[{role:'user',content:'first',timestamp:1},saved,JSON.parse(JSON.stringify(second)),
    {role:'toolResult',toolCallId:'deep-tool',toolName:'read',content:[{type:'text',text:'remote'}],isError:false,timestamp:3}]},100,
    async wire=>{
      const a=JSON.parse(wire.body).messages.filter((m:any)=>m.role==='assistant');
      assert.deepEqual(a.map((m:any)=>m.reasoning_content),['private first','private tool']);
      return {status:200,headers:{'content-type':'text/event-stream'},body:sse({content:'done'})};
    },()=>{}).result();
  const disabled={...deep,thinking:'disabled' as const,reasoning_effort:null};
  await providerStream(disabled,{messages:[{role:'user',content:'switch check only',timestamp:1}]},10,async wire=>{
    const p=JSON.parse(wire.body);assert.deepEqual(p.thinking,{type:'disabled'});assert.equal(p.temperature,.2);
    return {status:200,headers:{'content-type':'text/event-stream'},body:sse({content:'off'})};
  },()=>{}).result();
});

test('reasoning replay follows locked Pi eligibility without deleting aborted/error records',async()=>{
 const deep:ProviderBinding={...binding,provider:'deepseek',model_id:'deepseek-flash',thinking:'enabled',reasoning_effort:'high',compat:{...binding.compat,supportsReasoningEffort:true,requiresReasoningContentOnAssistantMessages:true}};
 const complete=await providerStream(deep,{messages:[{role:'user',content:'first',timestamp:1}]},100,async()=>({status:200,headers:{'content-type':'text/event-stream'},body:sse({reasoning_content:'complete private reasoning',content:'complete answer'})}),()=>{}).result();
 const aborted={...JSON.parse(JSON.stringify(complete)),stopReason:'aborted',errorMessage:'Retained interrupted generation',content:[{type:'thinking',thinking:'partial private reasoning',thinkingSignature:'reasoning_content'}]};
 const errored={...JSON.parse(JSON.stringify(aborted)),stopReason:'error',content:[{type:'thinking',thinking:'errored private reasoning',thinkingSignature:'reasoning_content'}]};
 const context:any={messages:[{role:'user',content:'first',timestamp:1},JSON.parse(JSON.stringify(complete)),{role:'user',content:'interrupted',timestamp:2},aborted,{role:'user',content:'error',timestamp:3},errored,{role:'user',content:'new task',timestamp:4}]};
 const original=JSON.stringify(context);let calls=0;
 const result=await providerStream(deep,context,100,async wire=>{
  calls++;const p=JSON.parse(wire.body);assert.deepEqual(p.messages.filter((m:any)=>m.role==='assistant'&&m.reasoning_content).map((m:any)=>m.reasoning_content),['complete private reasoning']);
  assert.ok(!JSON.stringify(p).includes('partial private reasoning'));assert.ok(!JSON.stringify(p).includes('errored private reasoning'));
  return {status:200,headers:{'content-type':'text/event-stream'},body:sse({reasoning_content:'new private reasoning',content:'new answer'})};
 },()=>{}).result();
 assert.equal(result.stopReason,'stop');assert.equal(calls,1);assert.equal(JSON.stringify(context),original);
 assert.equal(context.messages.filter((m:any)=>m.role==='assistant').length,3);
});
