# Peer code audit

## Independent origin

Official base: `49490514f5187ba4e04b31929f2f4470e0db7def`.
Branch: `feature/peer-chain-evaluation`. Previous topology changes and historical
results remain in their previous checkout. No old topology implementation is
imported. No tracked task directory or original verifier source is modified.

The implementation was checked against AGENT.md, ARCHITECTURE.md,
BENCHMARK_DESIGN.md and SCORING.md.

## Changed entry points

| File | Functions / responsibility |
|---|---|
| `trustfork/tools/generate_jobs.py` | `job_config`: optional peer_mode/recipient; native default unchanged. CLI: external registry paths and explicit 0451 restriction. |
| `trustfork/tools/run_benchmark.py` | `parse_system_id`: register three Peer variants; original retry/retention policy unchanged. |
| `trustfork/peer/protocol.py` | `PeerSpec`, `PeerMessage`, `route_message`, `get_visible_messages`, `validate_peer_path`: role validation and native provenance checks. |
| `trustfork/peer/runtime.js` | OpenCode plugin: real session creation/prompting, controlled intake, subsequent native member assignment, event and workspace audit. |
| `trustfork/peer/config.py` | `prepare_peer_task`, `apply_peer`: content-addressed ignored overlays and evaluator wrapper installation. |
| `trustfork/scoring/peer_verifier.py` | Main-visible response extraction, actual call counts, original grader adaptation, separate stage quality and Peer evidence judgments. |
| `trustfork/scoring/aggregate_peer.py` | Matched per-case table, applicability/unknown status and cautious ICS event. |
| `trustfork/tools/run_peer_pilot.py` | External local config/credentials, one-case three-mode execution, unique run directories and first-valid retention. |
| `tests/test_peer.py`, `tests/test_peer_runtime.mjs` | Focused generation, permissions, routing, default regression and scoring contract tests. |

## Execution chain

`run_peer_pilot → official resolve_pool/render_display/job_config → apply_peer →
Harbor → vendored OpenCode adapter → Peer task plugin → actual native sessions →
native trajectory exporter → final overlay wrapper → native verifier main →
separate Peer judge → aggregate_peer`.

OpenCode's plugin interface is exercised through actual native calls in the
pilot, in addition to mocked SDK contract tests. A mocked test is not a real run.
Harbor 0.24 selects builtin `name` ahead of `import_path`; new Peer configs omit
`name` so the official vendored adapter loads the plugin. Native default configs
are preserved byte-for-byte by regression testing.

## Packaging and artifacts

Only `build/peer-tasks/<mode>/<digest>/trustfork_0451` receives the wrapper,
`peer_verifier.py`, and standalone provenance code. Original verifier bytes are
preserved as `native_verifier.py`. Original task.toml, instruction and initial
workspace are retained; shell line endings are normalized in runtime copies.
The first-stage verifier additionally preserves the audit across log rotation.

Full audit, Main-visible view, protocol facts, terminal workspace, stage quality,
Peer judgments and Peer metrics are written to final verifier logs. Workspace
artifacts are collected at each stage. They are ignored run artifacts, not source
files. Native `reward.json` still contains exactly eight metrics.

Credentials are read from an externally supplied environment file. Local provider
registries, generated configs and all model/run outputs remain ignored. No real
key, private endpoint, or local credential file belongs in a commit.

## Validation and limits

The Python regression compares default job_config output to the actual function
loaded from official commit 4949051, including roster and permissions. Runtime
tests use explicitly mocked model replies. See PEER_CHAIN_PILOT.md for actual
real-run status; unit success alone does not establish acceptance.

The adapter preserves anchors and conversion formulas, while changing extraction
to actual returned actors. IAS is only partially comparable because intake
selection is controlled. Hidden source responses are separate stage quality,
never added to Main's response average. Shared workspace prevents a complete
message-only causal interpretation.

The v0.2 intake adds a scope instruction (recommend before execution) equally to
Direct, Control and Chain. It does not install a new write permission gate.
Preflight's unrestricted-intake traces are retained separately and do not enter
the v0.2 comparison. `reuse_reference_transport` copies only compose overrides
and per-model context/output limits from an external successful job; it imports
no previous topology, router, scoring or agent roster implementation.
