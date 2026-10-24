# TrustFork v9 offline implementation report

Protocol: `dynamic-join-v9-trajectory-portfolio`. Source revision:
`49490514f5187ba4e04b31929f2f4470e0db7def`. Backend: `docker-direct`.
Development branch: `research/trustfork-dynamic-join-offline`.

This report describes executable engineering checks, not model behavior or
research results. Real model requests: **0**. Real judge requests: **0**.

## Stage 1 — source locks and direct Docker

Implemented a separate runtime without changing the original Harbor/Pi entry,
source tasks, or scoring entry. All 30 original source cards are explicitly
mapped to their unique M0/G1/free/P0 deployment; mappings include stage briefs,
original assets, resources, services, goal boundaries and capability statuses.
Only original `environment/` content is copied into generated build contexts.
Evaluator-only `tests/` files and control files are not task mounts.

52 fixed-revision metadata discrepancies were individually audited. Both the
metadata and observed bytes match their fixed Git blobs. Each exception binds
revision, source path, metadata hash, declared hash, observed hash, and checked
deployment relationship. Unknown third hashes are rejected. The historical
cause is UNKNOWN; CRLF conversion does not explain these differences. Neither
original assets nor their declarations were rewritten. See the versioned
`source_errata.reviewed.json` and reproduction tool `audit_dynamic_sources`.

The direct Docker backend uses argument arrays, checks the audited base image
ID, preserves original services and task files, and generates a unique Compose
project per branch. Task commands run only inside the shared branch container.
Operation claims persist prepared/started/completed/effect_unknown states;
completed requests return their recorded result, while uncertain effects cannot
be blindly replayed. Concurrent operations retain overlap intervals.

Validation completed on the original task images:

| Check | Outcome |
|---|---|
| Foundation unit tests | 7 passed |
| Actual Docker integration tests | 5 passed |
| Original p001 service and remote filesystem/process operations | passed |
| Task container mounts and CPU/memory checks | passed; no mounts, 2 CPU/4 GiB |
| Lost-ACK write replay | passed; effect occurred once |
| p001/p024/p028 executed filesystem restoration | passed; independent restored container and equal fingerprint |
| Background write after cutoff | passed; paused environment remained unchanged |

The first run found diagnostic-code, path-format and Docker 29 commit-output
issues. These were fixed before rerunning. Docker snapshots explicitly do not
save RAM. Restoration is limited to a committed filesystem with quiescent work
processes and the original declared, file-backed restartable mock service.
Unclassified live processes or modified service code/config produce
`restore_unsupported`; no claim of arbitrary application/RAM restoration is made.
Four-card L protocol validation remains a later-stage requirement.

## Stage 2 — Pi and dynamic teams

The passive JSONL bridge drives real Pi core for exactly one response and its
complete tool batch per host permit. Python owns the only ready queue. Main has
coordination tools; Sub actors retain all seven original work tools and peer
communication. Initial planning enables registration tools only. Default SDK
provider retries, automatic compaction, extensions, model catalog refresh and
real provider access are disabled. Synthetic streams are explicit, never failure
fallbacks. Actual provider inputs, Pi events and Docker operations are recorded.

The user-authorized remote path repairs are pinned to Pi 0.84.1 and 14 exact
implementation/declaration hashes. They cover grep process creation, read path
existence, the shared write/edit canonical-path queue, and find's process and
git-ancestor existence calls. Native search, read, edit, write, error and
truncation logic stays in Pi. See SDK_Compatibility_Decisions.md for negative
probes and accepted changes. Runs require a fixed-hash public fd 10.3.0 binary;
they do not auto-download it or change the audited base image.

Implemented atomic admission, S/F/L scheduling, per-recipient FIFO and actual
exposure receipts, dynamic profiles and all specified supplement settings,
private goal binding, durable complete idle checkpoints, finite host retries,
shared budgets and explicit stage/finalization barriers. Refusal and F recruiting
neither candidate remain valid behavior. An unfinished old invocation cannot
continue into a new epoch. Original persistent service/files remain; tracked
nonbaseline background workers are stopped at a stage boundary.

Observed validation:

| Command / evidence | Actual result |
|---|---|
| `pytest tests/dynamic/unit ... test_session_contracts.py test_late_join.py -xq` | 38 passed; 32 unit, 2 real Pi, 4 real Docker/Pi L cases |
| `npm --prefix trustfork/runtime/dynamic run typecheck` | passed |
| `npm --prefix trustfork/runtime/dynamic run test:contract` | 3 passed, 0 skipped |
| Real Docker/Pi remote tool semantics | 4 passed; native grep/find oracle, bash truncation, symlink queue |
| Real common-prefix four-condition S and F no-recruit tests | 2 passed |
| Independent `npm ci --offline` | passed; idempotence, hash/version rejection, original SDK unchanged |
| L p004/p006/p008/p028 | executed old-member writes persisted in independent restored branches; original services retained |

Initial test failures exposed Docker commit output, hidden host path checks and
the rg directory omission; implementation defects were fixed. Two later test
assumptions were corrected against SDK source: empty chats can have a config leaf,
and skills are shown only when read is active. Tests now assert real behavior.
No failing test is counted as passed; full final acceptance remains stage 4.

The user accepted separate original-case coverage: p028 has one `ask` stage,
`new_session=false`; p024 has three stages with `new_session=true` on its final
stage. Memory and session-switching acceptance will cite different cases.
No original card or research matrix is modified.

## Stage 3 — frozen scoring, plans and tables

Implemented formal delivery extraction, identity-blind response inputs and a
complete Main-orchestration trajectory view with only the separately bound
private goal removed. Original rubric text and pure eight-score functions are
reused. Partial response judging never produces a complete mean; no response,
unknown, not annotated and judge error retain different states. Peer/team
extensions stay separate from original scores. Goal sensors distinguish prejoin,
ever observed, terminal and new postjoin effects; temporal order is not causality.
Dynamic Unicode claims are uncapped and distinct from original response claims;
consumption, quotation, rejection, planned adoption, action and recovery differ.

The static matrix contains exactly 1,664 unique planned branches in 440 blocks:
392 four-condition blocks and 48 two-condition blocks. S primary=832, F primary=416,
mechanism sample=144, separate history plans=16 and smoke plans=32. Actual run and
checkpoint IDs remain null in plan-only output. Frozen source/model/profile/goal/
prompt/scorer references are explicit. Exact API bindings and judge capacity
remain unresolved; plan rows are not presented as executed trials.

The five-table pipeline writes JSON and CSV plus analysis metadata and frozen
score inputs. It uses complete four-condition blocks, averages layouts within
card and then weights cards equally. Bootstrap uses 10,000 source-card resamples,
seed 20261024; both Mains share card draws. The S confirmation family is exactly
two Mains by IAS/SAF/VF/EI, with additional 99.375% intervals at quantiles
0.003125/0.996875. Missing blocks, partial scores, unknown binary bounds and
unannotated denominators are retained. Additional repeats do not enter primary
analysis. Formal analysis requires the frozen planned universe and rejects all
synthetic inputs. Shared prefix attempts are billed once; branch-equivalent costs
are separate and unknown costs do not become zero.

Observed checks:

| Command / evidence | Actual result |
|---|---|
| `pytest tests/dynamic/unit -q` | 47 passed, 0 skipped |
| `generate_dynamic_manifest --plan-only` | 1,664 branches / 440 blocks; executed=0 |
| `run_dynamic --mode scripted-test --case p001 --protocol S --conditions HP HA MP MA` | 4 valid synthetic branches, real Pi + Docker |
| Same CLI, p024 / F | 4 valid synthetic branches through original three stages |
| `aggregate_dynamic --mode test-fixtures` over these eight runs | five JSON/CSV files, synthetic watermark; 8 runs selected |
| Offline preflight | native Linux daemon, audited image, 30 mappings, 14 SDK hashes and fd hash passed |

The eight-run fixture has no supplement runs, so table 5 contains no observation
rows. Unit fixtures separately exercise nonempty baseline-linked supplements,
F no-recruit denominators, missing-block sensitivity and prefix cost accounting.
Fixed numeric judge values verify arithmetic/data flow only; they are not
judgments of those scripted agents. No semantic annotations were invented.

The source does not define a sufficiently audited base-task/family grouping.
That mapping and family-level sensitivity remain UNKNOWN/BLOCKED; source-card
bootstrap must not be advertised as establishing independence of templates.
Complex goal predicates remain `not_annotated`, with coverage reported.

## Stage 4 — final offline acceptance and coverage limits

Offline acceptance has finished for the implemented controller and the explicit
fixtures below. Formal API execution remains disabled. The final changes add
real-backend edge cases, conservative unknown-state handling, startup-slice
events, reproducible capability evidence and usage instructions. They do not
change original cards, injection text, permissions, enrollment timing or the
research matrix. The scheduler still permits independent per-file tool queues;
no global tool serialization was added.

### Executed checks

All commands use the existing Linux Python 3.12 environment and audited Node
tools described in README.md. Tests invoke real Pi 0.84.1 and the original Docker
task environments with explicitly scripted provider responses. No original task
`tests/test.sh`, real model provider or network judge was invoked.

| Check / retained local evidence | Actual final outcome |
|---|---|
| TypeScript `run typecheck` | passed |
| Node `run test:contract` | 4 passed, 0 skipped |
| Full Python unit/integration group; `build/dynamic/final-pytest.xml` | 77 passed, 0 skipped; 729.59 seconds |
| Scoring, backend and goal follow-up; `final-followup.xml` | 57 passed, 0 skipped |
| Startup-slice follow-up; `final-startup.xml` | 49 passed, 0 skipped |
| Final backend group plus targeted correction; `final-services.xml`, then `final-services-fixed.xml` | all 7 backend tests have passing final outcomes, 0 skipped |
| Distinct Python tests across those reports | 79; overlapping reruns are counted once |
| All-case materialization; `build/dynamic/final-materialized` | 30 mapped, 0 blocked |
| Offline preflight | passed for daemon, audited image, source locks, SDK patches and fd; formal readiness remains false |
| Separate clean `npm ci --offline` reproduction | all 14 locked files reproduced; idempotence and unknown version/hash rejection passed; independent original SDK unchanged |

The first final backend pass exposed a test assumption: it searched for
`python /opt/mock-api/app.py`, whereas the original Compose command is
`python3 /opt/mock-api/app.py`. The test now matches that original command.
Its targeted rerun verifies that killing that actual service leads to
`service_not_ready`. The failed attempt remains in its original JUnit file and
is not counted as a pass. An earlier image test fixture also contained an invalid
PNG; native and remote Pi returned the same image error. A valid CRC-checked PNG
now tests the positive image path without changing SDK image handling.

The final checks include the following concrete behaviors:

| Behavior | Implementation | Executed evidence |
|---|---|---|
| All seven tools operate inside the task; no host-path fallback | `pi_bridge.ts`, `remote_tools.ts`, locked SDK callbacks | `test_pi_bridge.py`, `test_remote_tool_semantics.py`; native search/read oracles, host traps, symlink same-file queue and cross-file overlap |
| Independent S conditions share identical pre-q Main input | `pi_dynamic.py`, `scheduler.py`, `pi_client.py` | `test_dynamic_protocol.py`; HP/HA and MP/MA actual requests match before first q execution, excluding SDK message timestamps only |
| F no-recruit behavior and unfinished startup work remain valid | `membership.py`, `scheduler.py` | protocol and runtime-edge tests; six actual requests continue beyond the initial four-request slice; no message is fabricated |
| L branches restore actual old-member work | `environment.py`, `lifecycle.py`, `checkpoints.py` | `test_late_join.py`; p004/p006/p008/p028 old-member writes persist in independent branches |
| Original memory and session-switch behavior | `pi_bridge.ts`, `pi_dynamic.py` | p028 original memory is actually read into a later request; p024 separately covers three original stages, retained chat and final `new_session=true` reset |
| Tool cancellation, stage boundaries and final freeze | `environment.py`, `lifecycle.py`, `scheduler.py` | actual cancelled process has no late write; old-epoch background work stops; queued messages migrate once or are cancelled according to reset; frozen workspace and mock state do not change |
| Original mock data and supported restore boundary | `environment.py` | original HTML bytes preserved over HTTP; mutated file-backed mock data survives restore and is served over HTTP; modified service config is rejected as `restore_unsupported` |
| State evidence differs from adoption or attribution | `goal_observer.py`, `trajectory_observer.py`, `dynamic_pipeline.py` | actual p001/p028 damage and repair, prejoin damage, unknown baseline and duplicate-name cases; no claim that temporal order proves q caused damage |
| Complete frozen scoring, tables and synthetic rejection | `dynamic_adapter.py`, `dynamic_pipeline.py`, `aggregate_dynamic.py` | unit tests and the explicit CLI fixtures below; incomplete judgments and missing annotations remain missing |

The original p006 skill is not automatically registered by the unchanged SDK
discovery/settings in its task image: the actual original discovery result was
an empty skill list. It remains readable at its original workspace path. Tests
read its unmodified body through Pi and verify that body in the next actual
provider input. No new catalog registration, relocated skill or invented stage
was used to manufacture acceptance.

### Explicit CLI fixtures and analysis output

The retained `build/dynamic/acceptance-v9/scripted` fixture contains 10 valid
synthetic branches: p001/S with all four conditions, p024/F with all four
conditions, and a p006 primary/r70 pair. The latter two branches reuse the same
actual prefix and Docker checkpoint, and the supplement resolves its actual
primary baseline run ID. Historical content in this fixture is explicit test
data; actual historical task executions equal zero.

The latest scorer produced five JSON and five CSV files under
`build/dynamic/acceptance-v9/tables-final-reviewed`, plus analysis metadata.
Table row counts are 4, 4, 9, 40 and 2. The two table-5 rows are a matched
supplement observation and its panel summary. These supersede the earlier
eight-run fixture described in stage 3. Fixed numeric judge values and scripted
responses validate data flow and arithmetic only. They cannot be reported as
model performance, attack success, adoption, safety or research findings.

The final static plan still contains exactly 1,664 unique branches in 440
blocks; executed formal branches equal zero. Actual run/checkpoint identifiers
remain unset in plan-only output. Planned or synthetic rows do not satisfy
formal execution denominators.

### Request and filesystem isolation evidence

`build/dynamic/network-guard-audit.json` records 452 guard receipts from 52
receipt files and 141 deduplicated scripted T3 completions in the CLI fixtures.
The raw 452 receipts and their source-file hashes are retained in
`network-guard-receipts.jsonl`, so temporary-test retention cannot erase this
audit evidence. Positive runs recorded zero outbound attempts and zero host-work
attempts. Real model requests and real judge requests are both zero. The negative
Node test deliberately attempted one fetch and verified interception before
connection; that attempt is not represented as zero. Dependency retrieval and
Git traffic are separate from provider/judge execution.

The actual repository resides on the WSL Linux ext4 filesystem, as independently
checked with `pwd -P` and `df -T .`. It was not moved. The first implementation
commit has the exact audited original base as its parent. All files tracked at
that base remain byte-for-byte unchanged; original task assets and the original
Harbor/Pi/scoring entry are intact. Generated task exports, runs, builds, local
dependency trees and raw test data stay outside Git. Only the implementation
branch is updated; the earlier pilot and environment-report branch are unchanged.

### Capability limits and unfilled definitions

The authoritative current overlay is
`trustfork/config/dynamic/case_readiness.json`, reproduced from explicitly cited
JUnit reports by `update_dynamic_readiness`. See Case_Capabilities.md for all
30 rows. Static source/assets/public packets pass for all 30 cards. Actual
initial and executed filesystem restores are verified for six:
p001/p004/p006/p008/p024/p028. The other 24 restore/runtime statuses remain
UNKNOWN or not tested. Restore covers quiescent files plus the original declared
file-backed restartable service, not arbitrary live process memory. Final exports
cover workspace, original home assets, mock files/logs and Docker diff metadata;
unlisted file contents are not claimed to have universal forensic coverage.

Six cards have deterministic contact/file-deletion predicates:
p001/p004/p008/p013/p014/p028. Actual goal-state change/repair/prejoin attribution
was tested on p001 and p028. The other four predicates are defined but not
runtime verified. Twenty-four complex boundaries require semantic annotation
and sufficient object/service evidence; they remain `not_annotated`, not zero.
Base-task/family grouping is UNKNOWN, family-level sensitivity is BLOCKED, and
second-annotator reliability has not been measured.

The executable bridge currently exposes scripted execution only. Real provider
transport and judge connections remain disabled and need a future implementation
and live compatibility check under separate authorization. Supplying an alias
alone will not enable real API runs. Fourteen precise model binding fields remain
unresolved across the two model aliases: provider, base URL, model ID, key
environment-variable name, context window, maximum output tokens and supported
parameters for each. Exact judge binding/capacity, actual H1/H2 histories and the
32 paid smoke branches are also not executed or resolved. No research setting
was filled in by assumption to hide these limits.

Stage commits on `research/trustfork-dynamic-join-offline`:

1. `6c72edbf2fb17f81750e44b9398d67775a8f0b7e` — source locks and Docker foundation.
2. `03c9d3e3a6ff5809c7b33956e994565c9312eb32` — Pi transport and dynamic teams.
3. `07a48e587a77038ee66f3bdce63855d3ccd73199` — scoring, paired plans and tables.
4. The commit containing this final section — offline acceptance and capability evidence.

Work stops after the final ordinary push. No live preflight, paid smoke,
discovery or confirmation experiment has been started.
