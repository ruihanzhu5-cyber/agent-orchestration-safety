# TrustFork Topology Code Audit

Status: source audit complete; topology implementation and live validation are tracked separately.

## Baseline and scope

Baseline HEAD: `49490514f5187ba4e04b31929f2f4470e0db7def`. The working tree already contained changes to `scoring/verifier.py`, `tools/ensure_base_image.py`, `tools/generate_jobs.py`, and `tools/run_benchmark.py`; these were preserved and backed up in the ignored `build/topology-preexisting/preexisting.patch`. Work proceeds on `feature/trustfork-topology-benchmark`.

## Audited call graph and ten required answers

1. **Main initialization:** `trustfork/tools/generate_jobs.py:job_config` selects the Harbor import path and orchestration model. `opencode_roster` defines the `orchestrator` primary profile. `trustfork/agents/opencode.py:OpenCode.run` writes the config and invokes `opencode --model=... run --agent orchestrator`. Harbor constructs the installed agent in `harbor/trial/trial.py:Trial._init_agent` through `AgentFactory`; `_setup_agent` installs it and `_run_agent_phase` executes it.
2. **Four candidates:** `resolve_pool` binds actual backbones; `render_display` produces labels independently; `opencode_roster`, `pi_roster`, and `openclaw_roster` install models, descriptions and tool permissions. `generate_jobs.main` injects `actor_goals.json`'s private prompt into exactly the focal slot. Displayed labels never change endpoints.
3. **Selection:** the orchestration LLM chooses a candidate through its harness-native tool using the displayed roster. It is not a Python ranking algorithm. OpenCode advertises descriptions in the `task` tool, generated from agent profiles.
4. **Invocation:** OpenCode uses `task(subagent_type, prompt, description, task_id?)`; Pi uses `Agent`, `get_subagent_result`, and `steer_subagent`; OpenClaw uses `sessions_spawn`. These have different scheduling, resume and result delivery semantics. A change to one does not implement the others.
5. **Return into Main context:** the pinned OpenCode `TaskTool` creates/resumes a child session, runs its configured agent, and wraps its final text as the task tool result. `OpenCode._database_assistant_step` preserves that actual root tool observation and links `sessionId` to a child trajectory. Intermediate child reasoning/tool outputs are not automatically the same as Main-visible task output.
6. **Peer calls:** OpenCode candidate profiles disable `task`; original depth is one. Pi sets `maxSubagentDepth=1`, a strict four-agent roster and disables scheduling. OpenClaw patches the spawn schema/allowlist and restricts children to the configured candidates. Native peer delegation is not an interchangeable cross-harness API. A runtime router must perform peer forwarding explicitly.
7. **Bypasses:** candidates share `/workspace`, mock service state and the container OS. Memory files persist across task sessions. Multi-step task scripts copy earlier ATIF snapshots into `/workspace/.trustfork-harness/trajectories`, a pre-existing visibility path. Candidate shell/read permissions may also expose harness/config/log files. Message routing therefore cannot claim complete information isolation. Main itself has only delegation tools. The extension preserves workspace access and reports observed/potential bypasses.
8. **Verification/execution authority:** Main encodes roles and delegated scope in native task requests and may select follow-up workers/verifiers. Candidates retain their ordinary tools and can mutate the workspace during their work; there is no original deterministic final-approval gate. Original Main decides the final response after returned evidence. The extension must not claim that recommendations imply approval or silently add a new security gate.
9. **Trajectory capture:** Harbor `Trial._sync_agent_output` downloads native logs and calls `_populate_agent_context`; the adapter's `populate_context_post_run` exports ATIF before verification. OpenCode `_load_database` reads session/message/part tables; `_convert_database_to_trajectory` recursively builds child trees, token metrics and actual tool observations. Pi converts JSONL/native child sessions; OpenClaw converts its gateway/native session exports.
10. **Verifier:** source `trustfork/scoring/verifier.py` is copied into task tests by `materialize_tasks.py`. `trajectory` merges session snapshots; `_extract_task_call_stats` reads root delegation tools; `extract_task_responses` attributes root tool observations by profile arguments; `extract_recursive_subagent_traces` reads child tools; `snapshot_workspace` captures terminal files. Two existing judge passes and `build_benchmark_scores`/`reward_from_benchmark_scores` produce unchanged eight metrics. Multi-hop routing needs factual call/response normalization and explicit recipient visibility; synthetic Main observations would be misleading.

Cross-harness entry points: `Pi._install_trustfork_config` installs the roster before `Pi.run`; `Pi.populate_context_post_run` exports native sessions. OpenClaw's `_trustfork_profile_plugin_source` and `_install_trustfork_profile_plugin` build/install spawn restrictions before `OpenClaw.run`; `OpenClaw.populate_context_post_run` exports its native session tree. These implementations were audited, not extended for new topologies in this version.

## Harness support decision

First version: OpenCode 1.18.13 only for Chain/Debate. Original remains the existing adapter/config and verifier without a topology plugin. Pi/OpenClaw remain available for Original and must reject new topologies explicitly.

The existing OpenCode adapter already supports runtime plugin source through `opencode_plugins` and installs it in `_build_register_plugins_command`; reuse that extension point rather than replacing Harbor. The pinned plugin SDK provides native `client.session.create` and `client.session.prompt`, plus custom tool definitions. Runtime calls remain real OpenCode sessions with the original four agent profiles. Live task 0018 confirmed custom-task registration on the pinned binary for both Chain and Debate, including native session/message backing; offline mocks alone would not establish that compatibility.

## Scoring and visibility constraints

The original extractor assumes that each root delegation corresponds to one returned actor response. A topology call schedules four (Chain) or eight (Debate) real turns, while Main receives only the permitted final evidence. Normalization must enumerate those observed calls separately, retain true child records, and tell the judge which responses were delivered to whom. Original extraction, rubric and numeric conversion remain unchanged.

CAR requires contradicting evidence at the decision boundary. Full evaluator access to a hidden intermediate response does not establish Main exposure. Until visibility-sensitive comparability is established, report non-original CAR as not comparable/withheld, alongside the original judge diagnostics and explicit message-delivery observations; do not label it the same comparable CAR.

## Primary implementation references

- Repository: `trustfork/agents/opencode.py`, `pi.py`, `openclaw.py`; `trustfork/tools/generate_jobs.py`, `run_benchmark.py`, `materialize_tasks.py`; `trustfork/scoring/verifier.py`, `aggregate.py`.
- Pinned native task: https://github.com/anomalyco/opencode/blob/v1.18.13/packages/opencode/src/tool/task.ts
- Pinned plugin/tool API: https://github.com/anomalyco/opencode/blob/v1.18.13/packages/plugin/src/index.ts and `packages/opencode/src/tool/registry.ts`.

## Environment observation

At audit start Docker Desktop was installed but its daemon was stopped; Ubuntu 26.04 retained Harbor 0.24.0, while its Docker integration was initially unavailable. Starting the installed Docker Desktop restored the Docker engine (29.8.2) and WSL integration. The cached `trustfork-agents:tf-three-harnesses-v1` image was reused. The Original task subsequently completed with a valid score; live Chain calls also confirmed the pinned custom-tool/SDK registration. Per-mode completion and remaining checks are in `TOPOLOGY_PILOT_REPORT.md`.
