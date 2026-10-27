# Dynamic join: homogeneous offline implementation

Latest: [TH/TUL Judge 修复与冻结轨迹补评](Frozen_Trajectory_TH_TUL_Followup_20261027.md).

## Latest real API pilot — 2026-10-27

Read the [small API experiment report](Small_API_Collection_Report_20261027.md)
and its [curated evidence index](../../runs/published/small-api-collection-20261027/README.md)
first for the actual four-cell DeepSeek collection and frozen GPT core rescoring.
The report distinguishes complete, partial, not applicable and unvalidated metrics.
The offline/readiness statements in the historical reports below describe their own
delivery dates. Default configuration remains offline; the limited pilot used
explicit runtime authorization and does not enable future API runs.

The [2026-10-26 delivery report](Next_Round_Implementation_Report_20261026.md) records source commits,
actual validation coverage, call audits, readiness and reversible recovery.

The [homogeneous experiment and metric contract](Homogeneous_Experiment_And_Metrics_v1.md)
defines the current 1248-branch plan, four explicit history bundles, shared
prefixes, v2 metrics and independent Judge preparation. Real API execution stays
disabled; no smoke or formal matrix is started. The commands and eight-score
discussion below describe the retained legacy implementation unless explicitly
using the new profile. For new work, use the linked current contract and
`--team-model`, `--history-pair-id`, `--history-bundle` and `--prefix-artifact`.
Old P-layout execution requires `--legacy`; per-block history generation is
explicit exploration via `--generate-history-per-block`, not the frozen plan.

The [2026-10-25 framework repair report](Framework_Repair_Report_20261025.md)
records the pre-repair and final implementation commits, reversible restore
commands, I01–I12 evidence, offline validation, and the historical log gap.
Real model/Judge execution remains disabled and formal readiness is false.

The [second repair and API preparation report](Repair_And_API_Preparation_Report_20261025.md)
records startup/source/rescoring fixes and mock-tested provider/history/Judge
paths. [Run artifacts and logging](Run_Artifacts_And_Logging.md) describes the
new persistent campaign/index/archival interfaces and explicit frozen rescoring.
These changes do not authorize live requests or establish formal readiness.

The executable controller is `trustfork/agents/pi_dynamic.py`. It calls Docker
directly and a passive Pi 0.84.1 bridge. The original Harbor/Pi entry and source
tasks are unchanged. Read the implementation report and SDK compatibility
decisions before interpreting capability or readiness fields.

## Reproduce the locked dependencies

Use the already audited Linux environment. Dependency installation is explicit;
normal trials never install software or download tools.

```bash
source "$HOME/.local/share/trustfork-env/activate.sh"
source /mnt/d/envs/trustfork-linux/bin/activate
cd "$HOME/research/trustfork-original-clean-20261024"
npm --prefix trustfork/runtime/dynamic ci --no-audit --no-fund
python -m trustfork.runtime.dynamic.dependencies --install-fd
```

The npm postinstall checks Pi 0.84.1 plus original/patched hashes and applies only
the locked callback changes. Unknown bytes or versions fail. For a populated
cache, `npm ci --offline` was separately tested. fd is fixed at 10.3.0; its
official-release archive and extracted binary hashes are locked. The existing
audited base image is reused. Task tools execute in Docker, including existence,
canonical paths and search processes; there is no host fallback.

The first activation selects the audited Node tools; the second selects the
existing Linux Python 3.12 virtual environment. It does not move the repository
or install another environment. Keep both active for the commands below.

## Offline commands

```bash
python -m trustfork.tools.preflight_dynamic --mode offline --out build/dynamic/preflight.json
python -m trustfork.tools.materialize_dynamic --all-cases --out build/dynamic/cases
python -m trustfork.tools.generate_dynamic_manifest --legacy --plan-only --out build/dynamic/plan.jsonl
python -m pytest tests/dynamic/unit tests/dynamic/integration -q
npm --prefix trustfork/runtime/dynamic run typecheck
npm --prefix trustfork/runtime/dynamic run test:contract
python -m trustfork.tools.run_dynamic --mode scripted-test --legacy --layout P1 --generate-history-per-block --case p001 --protocol S --conditions HP HA MP MA --trial-workers 1 --out build/dynamic/scripted/p001
python -m trustfork.tools.run_dynamic --mode scripted-test --legacy --layout P1 --generate-history-per-block --case p024 --protocol F --conditions HP HA MP MA --trial-workers 1 --out build/dynamic/scripted/p024
python -m trustfork.scoring.aggregate_dynamic --mode test-fixtures --input build/dynamic/scripted --out build/dynamic/tables-fixture
```

Use new output directories for separate attempts; existing evidence is retained.
One task container group runs at a time. Scripted streams exercise real Pi core
and real Docker, with synthetic outputs and fixed numeric judge fixtures. They
do not measure a real model's task performance, safety, reputation response or
attack success. No original task `tests/test.sh` or network judge is invoked.

`run_dynamic` also accepts `--layout`, `--main-model`, `--panel`, `--strategy`,
`--repeat-id` and explicit F recruitment choices. These select frozen settings;
they do not execute the formal matrix. A `PiDynamic.run_block(..., prefix=...)`
call can reuse the same actual prefix for matched baseline/supplement branches.

## Evidence and analysis

Each successful branch has a manifest, exact actual provider inputs, Pi events,
formal deliverables, mailbox receipts, private binding hashes, remaining budget,
and frozen workspace/service exports. Scoring writes content-hashed full inputs,
eight score states, actor reports, dynamic claims and goal observations.
`network-guard.jsonl` records actual bridge guard receipts without keys or prompt
contents. Positive runs require zero outbound/host-work attempts. The negative
guard test deliberately makes a blocked attempt and proves it was intercepted.

The five JSON/CSV tables distinguish actual event counts from semantic labels.
K, harmful output, adoption and many goal boundaries require evidence-linked
annotations. Missing/unknown/unannotated values remain missing. Numeric test
fixtures are watermarked and refused by formal analysis, including attempts to
remove a run-level synthetic flag while retaining synthetic events.

Formal frozen-data analysis requires `--mode formal --plan <plan.jsonl>`. A full
planned universe makes entirely missing blocks explicit `not_run` rows. Without
`--plan`, fixture tables describe the input subset and make no matrix completion
claim. Paired estimates use source-card clusters, equal card weights and the
frozen bootstrap specification. Shared prefix costs and branch-equivalent costs
are separate. Actual baseline IDs are resolved from existing primary runs.

The authoritative current capability overlay is `case_readiness.json`; the
source catalog's embedded initial readiness is a historical mapping-time record.
Restore support means a committed filesystem plus declared file-backed restartable
services at a quiescent boundary. No RAM snapshot is claimed. Unclassified live
workers or changed service code/configuration are explicitly unsupported.

The bridge exposes explicit scripted, local HTTP mock and prepared API backends.
The provider backend uses the locked Pi SDK with a host HTTP relay; host task IO
and bridge network traps remain active. The real backend is disabled by default
and requires a new authorized phase, complete route/compatibility/capacity data,
independent price/rate/request limits and explicit run authorization. Filling a
model alias or detecting a key does not enable it. Live provider/history/Judge
behavior and legacy-versus-lossless scoring equivalence remain unverified.

New CLI surfaces (run `--help` for exact arguments) are `run_dynamic --mode
mock|api`, `--bindings`, `--request-ceiling`, `--allow-real-api`,
`--mock-responses`, and `--campaign`; `provider_preflight`, `judge_dynamic`,
`rescore_dynamic`, and `campaign_artifacts` are new commands. The preflight is
read-only/offline. Judge transport is separate from pure scoring. Existing
`--out` remains supported and refuses an existing run output before execution.

## Original resource semantics

p006's original workspace skill is readable at
`/workspace/skills/auto-updater/SKILL.md`. The unchanged Pi discovery function and
the task's settings return no automatically registered skills in this original
image. Tests retain that behavior and prove the original body enters a later
actual request through read. p028's original `MEMORY.md` is likewise actually read
and retained in a request. p028 is single-stage; original p024 separately tests
three stages, preserved chat and a real `new_session=true` reset.

## Offline diagnostics after the framework repair

Use an existing audited `o200k_base` tokenizer cache for capacity measurements.
The audit refuses a missing cache and never downloads it. The pinned tokenizer
version is in `trustfork/config/dynamic/requirements.lock`; this repair reused
the already installed environment.

```bash
: "${TIKTOKEN_CACHE_DIR:?Set an existing audited tokenizer cache directory}"
python -m trustfork.tools.audit_judge_input --input build/dynamic/scripted --out build/dynamic/judge-input-audit.json --include-long-fixture
python -m trustfork.tools.audit_risk_opportunities --input build/dynamic/scripted --out build/dynamic/opportunities
python -m trustfork.tools.audit_model_calls --root build/dynamic/scripted --out build/dynamic/call-audit.json
```

Message content and local tool/format schema token estimates are separate from
HTTP wire serialization size. Provider framing and effective route capacity
remain unknown until supported by evidence. The illustrative 128K/4096 comparison
does not authorize sending. Lossless decoding does not establish Judge scoring
equivalence.

The call audit uses actual request/provider events and deduplicated receipts,
including failed attempts. It ignores initialized guard counters and fixed run
summary zeros. Add `--guard-archive` for a saved receipt archive and
`--coverage-gap` for each known missing interval; unobserved history is not zero.
Scoring preserves previous artifacts in `legacy/` and immutable `versions/`.
Re-score frozen records after a scorer repair; do not repeat team behavior to
repair a Judge failure. Opportunity reports are passive and do not change agent
permissions, communication, or source-task access.
