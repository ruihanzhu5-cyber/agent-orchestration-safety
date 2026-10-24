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

## SDK compatibility decisions and remaining work

The real Pi 0.84.1 negative grep probe trapped local `rg` despite custom
Operations. The user authorized only a minimal version/hash-locked remote spawn
extension, with repository reproduction and real-Docker regression requirements.
It has not yet passed its acceptance tests; no seven-tool Pi pass is claimed.

A subsequent real-SDK read probe detected host `fs.access` before the custom
ReadOperations. Its negative result is reproducible with
`tests/read-contract-probe.mjs`. A separate minimal optional path-existence
callback has been proposed. This newly identified interface remains BLOCKED
pending the user's decision and regression validation. Independent modules
continue; no host fallback is enabled.

The user accepted separate original-case coverage: p028 has one `ask` stage,
`new_session=false`; p024 has three stages with `new_session=true` on its final
stage. Memory and session-switching acceptance will cite different cases.
No original card or research matrix is modified.

Stage 2 scheduling/Pi integration, stage 3 scoring/statistics, and stage 4 full
pipeline acceptance are still in development. Formal API execution remains
disabled and unresolved model IDs stay null.
