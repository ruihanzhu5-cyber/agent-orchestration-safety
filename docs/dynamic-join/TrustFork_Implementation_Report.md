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

Stage 4 final acceptance remains in progress. Formal API execution is disabled;
precise provider/endpoint/model/key-variable/capacity/parameter bindings, real
provider compatibility, actual H1/H2 histories, judge capacity and second-annotator
reliability still require the separately authorized future phase.

Committed stages so far: stage 1 `6c72edbf2fb17f81750e44b9398d67775a8f0b7e`,
stage 2 `03c9d3e3a6ff5809c7b33956e994565c9312eb32`.
