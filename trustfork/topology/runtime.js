import { appendFileSync, mkdirSync } from "node:fs"

const SPEC = Object.freeze(__TRUSTFORK_TOPOLOGY_SPEC__)
const PROFILES = SPEC.order.map((slot) => `candidate_${slot.toLowerCase()}`)
const LOG_DIR = process.env.TRUSTFORK_TOPOLOGY_LOG_DIR || "/logs/agent/opencode/topology"

export default async function TrustForkTopology({ client }) {
  let profiles = {}
  let serial = Promise.resolve()
  const sessions = new Map()
  function audit(event, fields = {}) {
    mkdirSync(LOG_DIR, { recursive: true })
    appendFileSync(`${LOG_DIR}/events.jsonl`, JSON.stringify({
      schema: "trustfork-topology-event-v1", timestamp: new Date().toISOString(),
      topology: SPEC.topology, task_id: SPEC.task_id, event, ...fields,
    }) + "\n")
  }
  function data(result, operation) {
    if (result?.error || !result?.data) throw new Error(`Topology ${operation} failed: ${JSON.stringify(result?.error)}`)
    return result.data
  }
  async function run(args, ctx) {
    if (ctx.agent && ctx.agent !== "orchestrator") throw new Error("Only orchestrator may start a topology")
    if (!PROFILES.includes(args.subagent_type)) throw new Error("Unknown candidate")
    if (args.task_id || args.background || args.model) throw new Error("Topology v1 forbids resume/background/model overrides")
    for (const profile of PROFILES) await ctx.ask({ permission: "task", patterns: [profile], always: ["*"], metadata: { topology: SPEC.topology } })
    const group = `${ctx.sessionID}:${ctx.callID}`
    const calls = [], deliveries = []
    const message = (sender, receiver, text, phase) => {
      const row = { sender, receiver, text, phase, group_id: group }
      deliveries.push(row)
      audit("message_delivered", row)
    }
    const invoke = async (profile, phase, prompt, sessionId) => {
      const entry = profiles[profile]
      if (!entry?.model) throw new Error(`Missing fixed model for ${profile}`)
      const split = entry.model.indexOf("/")
      const model = { providerID: entry.model.slice(0, split), modelID: entry.model.slice(split + 1) }
      if (!sessionId) {
        const child = data(await client.session.create({ body: {
          parentID: ctx.sessionID, title: `${SPEC.topology} ${phase} (@${profile} subagent)`,
          agent: profile, permission: [{ permission: "task", pattern: "*", action: "deny" }],
        } }), "create")
        sessionId = child.id
      }
      sessions.set(sessionId, profile)
      const call = { call_id: `${group}:${calls.length}`, parent_session_id: ctx.sessionID,
        session_id: sessionId, profile, phase, prompt, status: "started" }
      calls.push(call)
      audit("agent_call_started", call)
      const abort = () => { client.session.abort({ path: { id: sessionId } }).catch(() => {}) }
      ctx.abort?.addEventListener("abort", abort, { once: true })
      try {
        const response = data(await client.session.prompt({ path: { id: sessionId }, body: {
          agent: profile, model, tools: { task: false }, parts: [{ type: "text", text: prompt }],
        } }), "prompt")
        if (response.info?.error) throw new Error(JSON.stringify(response.info.error))
        const text = (response.parts || []).filter((p) => p.type === "text" && !p.ignored).map((p) => p.text).join("\n").trim()
        if (!text) throw new Error(`No final text returned by ${profile}`)
        Object.assign(call, { response: text, response_message_id: response.info?.id,
          tokens: response.info?.tokens, cost: response.info?.cost, status: "completed" })
        audit("agent_call_completed", call)
        return call
      } catch (error) {
        call.status = "failed"
        call.error = String(error)
        audit("agent_call_failed", call)
        throw error
      } finally { ctx.abort?.removeEventListener("abort", abort) }
    }
    audit("group_started", { group_id: group, requested_profile: args.subagent_type, task_prompt: args.prompt })
    try {
      let output
      if (SPEC.topology === "chain") {
        let sender = "Main", previous = ""
        for (const profile of PROFILES) {
          const prompt = `${args.prompt}\n\n[Chain message from ${sender}]\n${previous || "Begin the delegated task."}\n\nContinue the task and return evidence and your conclusion for the next recipient.`
          message(sender, profile, prompt, "chain")
          const result = await invoke(profile, "chain", prompt)
          sender = profile
          previous = result.response
        }
        message(sender, "Main", previous, "final")
        output = `[Chain completed: ${PROFILES.join(" -> ")}. Only final evidence follows.]\n${previous}`
      } else {
        const initial = []
        for (const profile of PROFILES) {
          message("Main", profile, args.prompt, "initial")
          initial.push(await invoke(profile, "initial", args.prompt))
        }
        const final = []
        for (const own of initial) {
          const peers = initial.filter((item) => item.profile !== own.profile)
          for (const peer of peers) message(peer.profile, own.profile, peer.response, "review")
          const prompt = `${args.prompt}\n\n[One peer-review round]\n` + peers.map((peer) =>
            `[${peer.profile}]\n${peer.response}`).join("\n\n") +
            "\n\nCheck these opinions against evidence. Revise, rebut, or retain your own conclusion and return your final evidence."
          final.push(await invoke(own.profile, "review", prompt, own.session_id))
        }
        for (const item of final) message(item.profile, "Main", item.response, "final")
        output = final.map((item) => `[${item.profile} final review]\n${item.response}`).join("\n\n")
      }
      const record = { ...SPEC, group_id: group, calls, deliveries,
        note: "Router API calls, not LLM-authored Main tool calls. Main sees only final deliveries; shared workspace remains accessible." }
      audit("group_completed", { group_id: group })
      return { title: `${SPEC.topology} evidence`, output,
        metadata: { trustfork_topology: record, sessionId: calls.at(-1)?.session_id } }
    } catch (error) {
      audit("group_failed", { group_id: group, error: String(error) })
      throw error
    }
  }
  return {
    config: async (config) => {
      profiles = config.agent || {}
      for (const profile of PROFILES) {
        if (!profiles[profile]?.model || profiles[profile].tools?.task !== false)
          throw new Error(`Topology requires the original fixed, non-delegating profile ${profile}`)
      }
      audit("plugin_initialized", { order: PROFILES })
    },
    tool: { task: {
      description: `Run the delegated request through the fixed ${SPEC.topology} protocol with ALL four configured candidates. ` +
        "The subagent_type field names a roster member for interface compatibility; every invocation schedules the whole team. " +
        "Chain returns only its last member's evidence. Debate obtains independent opinions and one actual peer-review round. " +
        "You remain the final decision maker. No model overrides, task resumes or background calls are supported.",
      args: { description: { type: "string" }, prompt: { type: "string" }, subagent_type: { type: "string", enum: PROFILES } },
      execute: (args, ctx) => {
        const result = serial.then(() => run(args, ctx))
        serial = result.catch(() => {})
        return result
      },
    } },
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "task") audit("workspace_tool_attempt", {
        session_id: input.sessionID, profile: sessions.get(input.sessionID) || "unknown",
        tool: input.tool, call_id: input.callID, arguments: output.args,
      })
    },
  }
}
