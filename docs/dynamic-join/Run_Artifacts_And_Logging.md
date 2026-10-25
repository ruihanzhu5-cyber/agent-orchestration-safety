# Run artifacts and logging

For the current 1248-branch homogeneous plan and explicit history/prefix
preparation, see [the current contract](Homogeneous_Experiment_And_Metrics_v1.md).
New campaign invocations validate source commit, configuration, mode and plan
factors; changed identities require a new campaign. The historical examples
below describe legacy/exploratory interfaces.

This is an engineering interface, not permission to run a model. Scripted and
mock execution remain available with `real_api_enabled=false`. A populated key
environment does not select API mode. Formal readiness remains false.

## Persistent location

Set `TRUSTFORK_ARTIFACT_ROOT` to an audited persistent directory outside the
checkout. Verify both Linux mount type and the Windows location of the WSL VHDX;
an ext4 `/home` path alone does not prove that its bytes are on the intended
drive. The local engineering report records the actual machine paths and free
space. Repository documentation uses variables, not personal paths.

```bash
: "${TRUSTFORK_ARTIFACT_ROOT:?Set the verified persistent artifact root}"
: "${BINDINGS:?Set the local binding JSON path; no key values in this file}"
python -m trustfork.tools.generate_dynamic_manifest --legacy --plan-only --out "$TRUSTFORK_ARTIFACT_ROOT/selected-plan.jsonl"
python -m trustfork.tools.campaign_artifacts create --campaign-id offline-smoke-example \
  --config "$BINDINGS" --plan "$TRUSTFORK_ARTIFACT_ROOT/selected-plan.jsonl" --mode scripted-test
python -m trustfork.tools.run_dynamic --mode scripted-test --legacy --layout P1 --generate-history-per-block --case p001 --protocol S \
  --conditions HP --trial-workers 1 --campaign offline-smoke-example
python -m trustfork.tools.campaign_artifacts index --campaign-id offline-smoke-example
python -m trustfork.tools.campaign_artifacts verify --campaign-id offline-smoke-example
```

`create` hashes configuration and plan; it does not execute the plan. The full
1664-branch plan is not a request count. The example runs only the explicitly
selected scripted block. Use a new campaign ID for an independent attempt.
`--out` remains supported; an existing run output is refused before starting Pi
or Docker. `--campaign` is new in this repair and derives a Windows-safe block
slug; the full logical ID remains in manifests. No artifact root is mounted into
the task. The task sees only its original case environment.

## Layout and provenance

```text
campaigns/<campaign_id>/
  campaign.json                 # source commit, dirty/config/plan hashes, mode/status
  plan.jsonl                    # selected plan, not an implicit execution request
  history/                      # H1/H2, isolated tasks and individual session carry
  blocks/<safe_block_slug>/
    history/                    # run_dynamic-owned reusable history, if present
    prefix/                     # existing shared prefix/checkpoint format
    late-prefix/                # existing L checkpoint format
    <condition>/attempt-<n>/
      run.json
      run_manifest.json
      events.jsonl
      control/                  # Pi sessions, bridge stderr, guard receipts
      environment/              # original exports and operation evidence
      scoring/versions/<id>/    # immutable score inputs/outputs
      scoring/current_version.json
  analysis/
  diagnostics/
  test-results/
  artifact-index.json
local-config/                   # local metadata only, no plaintext credentials
```

The existing block file organization is retained. The index records relative
path, size, SHA-256, role and available run/block/history/checkpoint/condition/
actor/stage/request/scoring identifiers. JSONL records retain the detailed
per-event identifiers; the index does not create another event authority.
Indexing records a symlink's type and target text/hash without following it,
including pytest's `current` directory aliases. External target contents are not
indexed or claimed as evidence. Verification detects alias replacement without
reading its target; a link hash is distinct from a file-content hash.

The same event ledger continues to own queued, claimed, submitted, successful,
stage and tool events. Pi `model_request_submitted` preserves the actual core
context; `provider_payload` records the locked SDK's exact converted payload.
`provider-requests.jsonl` owns HTTP attempt/response/error evidence, identified by
transport and request ID. It records failures, partial/unknown outcomes, usage
when supplied and unknown cost. No authentication headers or environment dump
cross the bridge. Credential values are excluded at the host transport boundary;
benchmark synthetic secrets are not blanket-redacted.

Pi's internal zero-price model fields are SDK placeholders, not endpoint price
evidence. Billing uses the host attempt journal and `provider_accounting` with
unknown cost. Missing usage stays null; a missing output count reserves the full
already-approved output allowance in the team budget. That reservation is marked
as conservative accounting, not reported provider usage.

## Conflict, recovery and archival

Existing campaigns and attempts are refused by default. `create --resume`
requires identical commit/dirty/config/plan/mode and verifies the saved index.
Completed attempts can be located and verified without rerunning them. Partial
attempts require reconciliation; this interface does not replay tools, HTTP
requests or earlier team turns to manufacture a complete run. Existing scheduler
checkpoints retain their own restore checks. A provider journal cannot be
reopened to silently reset its request/cost ceilings.

JSONL appends use a scoped file lock, one complete record and fsync. An
interrupted suffix is retained and blocks further appends; it is never promoted
to a successful event. Manifest/index writes use unique temporary files and
atomic replacement. Incomplete or corrupt inputs make verification fail; they do
not become zero calls or safe scores. Old runs are never automatically deleted.

```bash
python -m trustfork.tools.campaign_artifacts seal --campaign-id offline-smoke-example \
  --archive "$SECOND_LOCATION/offline-smoke-example.tar.gz"
```

`seal` refreshes and verifies the index, creates a non-overwriting archive outside
the campaign and writes its SHA-256 sidecar. Keep the source. Copy the archive
and sidecar to an independently managed second location and verify both the
archive hash and extracted index before treating that copy as a backup. This
repair does not upload, relocate or delete evidence.

## Judge and frozen rescoring

`judge_dynamic` is a separate transport command. It prepares response and
trajectory passes with original rubrics, exact schema instructions, independent
output reserve, route and hashes. The sender consumes the prepared `wire_payload`
without adding content. Unknown route/tokenizer/framing/output budget or overflow
blocks transmission; it never truncates, changes models or averages chunks.
Goal-state annotations can be connected through the original GoalSpec and the
versioned observer contract. The six predicates remain distinct from the 24
semantic cases; no absent judgment is filled with false.

The command writes a new Judge-attempt directory and a versioned annotation
sidecar. It does not overwrite the run's original annotations. To consume a new
sidecar explicitly:

```bash
python -m trustfork.tools.rescore_dynamic --run "$RUN/run.json" --mode formal \
  --reason 'Consume separately validated Judge pass for this frozen run' \
  --annotation-policy new --new-annotations "$JUDGE_ATTEMPT/scoring_annotations.json"
```

This future formal command refuses scripted/mock provenance. For an engineering
fixture use `--mode test-fixtures`, retaining its synthetic watermark. Default
scoring still enforces scorer lineage. Explicit rescoring records the original
and current scorer, raw run/manifest/events/archives/binding hashes, parent
version, annotation provenance and Judge request hashes. Default annotation
policy is pending. Reuse requires explicit matching compatibility evidence and
unchanged Judge/annotation semantics; it is not automatic re-Judging.

New score versions seal full event envelopes, including timestamps omitted from
the public Judge view, and validate workspace plus additional service archives.
A legacy score without that seal needs `--source-audit` pointing to a retained
original audit of both branch and prefix event bytes. Its original run bytes
must also be recoverable from the immutable summary or proved by that audit.
Without such evidence the result is `rescore_source_seal_unknown`; hashing
potentially changed files today is not a substitute for their original hashes.
Reuse additionally requires the exact original annotation hash and scorer to
match the parent, not only a statement that two recent scorers are compatible.

The full version is built in a private staging directory. Only a complete,
validated version is published; `current_version.json` is updated last. Failed
scoring leaves the old current version readable. Compatibility flat outputs are
not authoritative; read `versions/<id>` via the current pointer. Judge failure
can lead to another Judge attempt against the same frozen behavior, never a
replacement team trajectory.

## Audit and Git boundary

```bash
python -m trustfork.tools.audit_model_calls --root "$CAMPAIGN" --out "$CAMPAIGN/diagnostics/calls.json"
python -m trustfork.tools.audit_judge_input --input "$SAVED_SCORING_INPUTS" \
  --include-long-fixture --out "$CAMPAIGN/diagnostics/judge-capacity.json"
```

Use an existing audited `TIKTOKEN_CACHE_DIR`. Cache misses fail closed and never
download a tokenizer. The call audit uses retained submission/provider events,
host HTTP journals and guard receipts; initialized counters and fixed run-level
zeros are not proof. Known historical gaps stay UNKNOWN and are reported
separately from the current campaign.

Commit code, schemas, locks, small synthetic fixtures and engineering reports.
Keep credentials, personal machine paths, full Pi/provider logs, trajectories,
workspaces and result dumps local. Existing build/runs/results/outputs and `.env`
ignore boundaries remain in force; do not bypass them with `git add -f`.
