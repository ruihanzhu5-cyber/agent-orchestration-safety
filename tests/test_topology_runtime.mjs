// Mock SDK transport tests only. These are NOT benchmark/API results.
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

process.env.TRUSTFORK_TOPOLOGY_LOG_DIR = mkdtempSync(path.join(tmpdir(), "trustfork-topology-"))
const source = readFileSync(new URL("../trustfork/topology/runtime.js", import.meta.url), "utf8")
async function setup(topology, failAt = -1) {
  const spec = { topology, order: [..."ABCD"], task_id: "unit-test-only" }
  const encoded = Buffer.from(source.replace("__TRUSTFORK_TOPOLOGY_SPEC__", JSON.stringify(spec))).toString("base64")
  const factory = (await import(`data:text/javascript;base64,${encoded}`)).default
  const requests = [], creates = []
  const client = { session: {
    create: async (request) => { creates.push(request); return { data: { id: `s${creates.length}` } } },
    prompt: async (request) => {
      requests.push(request)
      if (requests.length === failAt) return { error: { message: "mock service failure" } }
      const text = `${request.body.agent}:${requests.length}`
      return { data: { info: { id: `m${requests.length}`, tokens: { input: 1, output: 1 }, cost: 0 }, parts: [{ type: "text", text }] } }
    },
    abort: async () => ({}),
  } }
  const hooks = await factory({ client })
  const config = { agent: Object.fromEntries([..."abcd"].map((slot) => [`candidate_${slot}`, {
    model: slot === "b" ? "p/model-b" : "q/model-q", tools: { task: false },
    ...(slot === "d" ? { prompt: "private-unit-goal" } : {}),
  }])) }
  const before = JSON.stringify(config)
  await hooks.config(config)
  assert.equal(JSON.stringify(config), before, "runtime must not mutate roster/goals/permissions")
  const ctx = { agent: "orchestrator", sessionID: "root", callID: "c1", ask: async () => {}, abort: new AbortController().signal }
  return { hooks, ctx, requests, creates, config }
}
const args = { description: "Test task", prompt: "User task", subagent_type: "candidate_a" }

test("chain forwards only predecessor text, creates four actual SDK sessions, returns D only", async () => {
  const s = await setup("chain")
  const result = await s.hooks.tool.task.execute(args, s.ctx)
  assert.equal(s.creates.length, 4)
  assert.equal(s.requests.length, 4)
  assert.match(s.requests[1].body.parts[0].text, /candidate_a:1/)
  assert.match(s.requests[2].body.parts[0].text, /candidate_b:2/)
  assert.doesNotMatch(s.requests[2].body.parts[0].text, /candidate_a:1/)
  assert.match(result.output, /candidate_d:4/)
  assert.doesNotMatch(result.output, /candidate_a:1/)
  assert.equal(result.metadata.trustfork_topology.deliveries.length, 5)
  for (const request of s.requests) assert.equal(request.body.tools.task, false)
  assert.deepEqual(s.requests[1].body.model, { providerID: "p", modelID: "model-b" })
})

test("debate executes four independent opinions and four real reviews of frozen initial peers", async () => {
  const s = await setup("debate")
  const result = await s.hooks.tool.task.execute(args, s.ctx)
  assert.equal(s.creates.length, 4)
  assert.equal(s.requests.length, 8)
  for (const request of s.requests.slice(0, 4)) assert.equal(request.body.parts[0].text, "User task")
  for (let i = 0; i < 4; i++) {
    assert.equal(s.requests[4 + i].path.id, s.requests[i].path.id)
    const prompt = s.requests[4 + i].body.parts[0].text
    for (let j = 0; j < 4; j++) if (j !== i) assert.ok(prompt.includes(`candidate_${"abcd"[j]}:${j + 1}`))
    assert.doesNotMatch(prompt, /candidate_[abcd]:[5-8]/)
  }
  assert.equal(result.metadata.trustfork_topology.deliveries.length, 20)
  for (let i = 0; i < 4; i++) assert.ok(result.output.includes(`candidate_${"abcd"[i]}:${i + 5}`))
})

test("unknown actors, direct child delegation and resume overrides fail closed", async () => {
  const s = await setup("chain")
  await assert.rejects(s.hooks.tool.task.execute({ ...args, subagent_type: "other" }, s.ctx), /Unknown candidate/)
  await assert.rejects(s.hooks.tool.task.execute(args, { ...s.ctx, agent: "candidate_a" }), /Only orchestrator/)
  await assert.rejects(s.hooks.tool.task.execute({ ...args, task_id: "secret-child" }, s.ctx), /forbids/)
})

test("partial SDK failure aborts the chain instead of fabricating later replies", async () => {
  const s = await setup("chain", 2)
  await assert.rejects(s.hooks.tool.task.execute(args, s.ctx), /failed/)
  assert.equal(s.requests.length, 2)
})
