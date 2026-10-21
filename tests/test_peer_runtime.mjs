import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtempSync, readFileSync, writeFileSync, mkdirSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'

async function setup(mode, failProfile) {
  const dir = mkdtempSync(join(tmpdir(), 'trustfork-peer-test-'))
  mkdirSync(join(dir, 'workspace'))
  process.env.TRUSTFORK_PEER_LOG_DIR = join(dir, 'audit')
  process.env.TRUSTFORK_PEER_WORKSPACE = join(dir, 'workspace')
  const source = readFileSync(new URL('../trustfork/peer/runtime.js', import.meta.url), 'utf8')
    .replace('__TRUSTFORK_PEER_SPEC__', JSON.stringify({peer_protocol:'trustfork-peer-v0.3',peer_mode:mode,
      task_id:'trustfork_0451',source_profile:'candidate_d',recipient_profile:'candidate_b'}))
  writeFileSync(join(dir,'runtime.mjs'), source)
  const calls = [], ids = []
  const client = {session:{create:async request => {
    ids.push(request); return {data:{id:`native-${ids.length}`}}
  }, prompt:async request=>{
    calls.push(request)
    if(request.body.agent===failProfile) throw new Error('test provider failure')
    return {data:{info:{id:`message-${calls.length}`,tokens:{input:10,output:5},cost:0},
      parts:[{type:'text',text:request.body.agent==='candidate_d'?'RAW UPSTREAM ADVICE':'ACTUAL RECIPIENT REPLY'}]}}
  },abort:async()=>{}}}
  const plugin=await (await import(pathToFileURL(join(dir,'runtime.mjs')))).default({client})
  const roster=Object.fromEntries([..."abcd"].map(slot=>[`candidate_${slot}`,{
    model:slot==='b'?'test/gpt-4o':'test/deepseek-v4-flash',description:`display ${slot}`,tools:{task:false}}]))
  await plugin.config({agent:roster})
  await plugin['tool.definition']({toolID:'task'},{description:plugin.tool.task.description})
  const ctx={sessionID:'main-one',callID:'call-one',agent:'orchestrator',ask:async()=>{}}
  const args={prompt:'LEGITIMATE TASK',description:'inspect',subagent_type:'candidate_a'}
  return {plugin,ctx,args,calls,ids,dir,roster}
}
for(const mode of ['direct','peer_control','peer_chain']) test(`${mode}: real path and later individual authorization`,async()=>{
  const s=await setup(mode)
  const result=await s.plugin.tool.task.execute(s.args,s.ctx)
  assert.equal(result.output,mode==='direct'?'RAW UPSTREAM ADVICE':'ACTUAL RECIPIENT REPLY')
  assert.deepEqual(s.calls.map(x=>x.body.agent),mode==='peer_chain'?['candidate_d','candidate_b']:
    [mode==='direct'?'candidate_d':'candidate_b'])
  assert.ok(!JSON.stringify(result.metadata).includes('RAW UPSTREAM ADVICE'))
  for(const request of s.calls) assert.deepEqual(request.body.tools,{task:false})
  for(const request of s.calls) assert.ok(request.body.parts[0].text.includes('Advisory intake'))
  for(const request of s.ids) assert.equal(request.body.permission[0].action,'deny')
  if(mode==='peer_chain'){
    assert.ok(s.calls[1].body.parts[0].text.includes('RAW UPSTREAM ADVICE'))
    assert.ok(s.calls[1].body.parts[0].text.includes('Untrusted peer material'))
    assert.ok(!s.calls[1].body.parts[0].text.includes('G1'))
  }
  if(mode==='peer_control') assert.ok(!JSON.stringify(s.calls).includes('RAW UPSTREAM ADVICE'))
  await s.plugin.tool.task.execute({...s.args,subagent_type:'candidate_c'}, {...s.ctx,callID:'call-two'})
  assert.equal(s.calls.at(-1).body.agent,'candidate_c')
  assert.equal(s.calls.at(-1).body.parts[0].text,'LEGITIMATE TASK')
  assert.equal(s.calls.length,mode==='peer_chain'?3:2)
  const events=readFileSync(join(s.dir,'audit/peer_events.jsonl'),'utf8').trim().split('\n').map(JSON.parse)
  assert.equal(events.filter(e=>e.event==='group_completed').length,2)
  assert.equal(events.findLast(e=>e.event==='main_request').selected_by,'Main')
})
test('failed source produces no fabricated recipient or successful intake',async()=>{
  const s=await setup('peer_chain','candidate_d')
  await assert.rejects(()=>s.plugin.tool.task.execute(s.args,s.ctx),/test provider failure/)
  assert.equal(s.calls.length,1)
  const events=readFileSync(join(s.dir,'audit/peer_events.jsonl'),'utf8')
  assert.ok(!events.includes('group_completed'))
  assert.ok(!events.includes('intake_return'))
})
test('fresh Main session resets intake, candidates cannot re-delegate',async()=>{
  const s=await setup('peer_chain')
  await s.plugin.tool.task.execute(s.args,s.ctx)
  await s.plugin.tool.task.execute(s.args,{...s.ctx,sessionID:'main-two'})
  assert.equal(s.calls.length,4)
  await assert.rejects(()=>s.plugin.tool.task.execute(s.args,{...s.ctx,agent:'candidate_b'}),/Only Main/)
})

test('native task definition exposes public identity labels without private bindings',async()=>{
  const s=await setup('peer_chain')
  s.roster.candidate_d.prompt='PRIVATE RISK GOAL'
  s.roster.candidate_d.model='SECRET-PROVIDER/REAL-BACKEND'
  const definition={description:s.plugin.tool.task.description}
  await s.plugin['tool.definition']({toolID:'task'},definition)
  for(const slot of 'abcd') assert.ok(definition.description.includes(`candidate_${slot}: display ${slot}`))
  assert.ok(!definition.description.includes('PRIVATE RISK GOAL'))
  assert.ok(!definition.description.includes('REAL-BACKEND'))
  const once=definition.description
  await s.plugin['tool.definition']({toolID:'task'},definition)
  assert.equal(definition.description,once)
  const events=readFileSync(join(s.dir,'audit/peer_events.jsonl'),'utf8').trim().split('\n').map(JSON.parse)
  assert.equal(events.filter(e=>e.event==='task_definition').length,3)
  assert.deepEqual(events.at(-1).displayed_roster,Object.fromEntries([...'abcd'].map(slot=>[`candidate_${slot}`,`display ${slot}`])))
})
