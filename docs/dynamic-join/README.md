# Dynamic join v9: offline implementation

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
python -m trustfork.tools.generate_dynamic_manifest --plan-only --out build/dynamic/plan.jsonl
python -m pytest tests/dynamic/unit tests/dynamic/integration -q
npm --prefix trustfork/runtime/dynamic run typecheck
npm --prefix trustfork/runtime/dynamic run test:contract
python -m trustfork.tools.run_dynamic --mode scripted-test --case p001 --protocol S --conditions HP HA MP MA --trial-workers 1 --out build/dynamic/scripted/p001
python -m trustfork.tools.run_dynamic --mode scripted-test --case p024 --protocol F --conditions HP HA MP MA --trial-workers 1 --out build/dynamic/scripted/p024
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

The bridge currently exposes scripted execution only. Real provider execution
and judge connections remain disabled: precise bindings, API format/retry/tool
compatibility, live history execution and judge capacity require the next
authorized phase. Filling a model alias alone does not enable API execution.

## Original resource semantics

p006's original workspace skill is readable at
`/workspace/skills/auto-updater/SKILL.md`. The unchanged Pi discovery function and
the task's settings return no automatically registered skills in this original
image. Tests retain that behavior and prove the original body enters a later
actual request through read. p028's original `MEMORY.md` is likewise actually read
and retained in a request. p028 is single-stage; original p024 separately tests
three stages, preserved chat and a real `new_session=true` reset.
