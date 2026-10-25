# Dynamic join: second repair and API preparation

Date: 2026-10-25. This is an offline engineering report. Real API execution and
formal experiments remain disabled; `formal_ready=false`. Mock results do not
establish model performance, history effects, Judge equivalence or attack rates.

## Source and reversible delivery

Repository: `ruihanzhu5-cyber/agent-orchestration-safety`. Work continues on
`fix/dynamic-join-audit-20261025`. The actual clean starting commit and fetched
origin head both were `37226afc4d8b94b5895cb32918f5345d76ec6e95`; their divergence
was 0/0. No pre-existing uncommitted work needed saving. The local backup tag
`backup/dynamic-api-preparation-20261025T130058Z` points to that exact start.

Final implementation commit: **1ba9d339520ffa7956375a3330676851790a02db**. The delivery commit
containing this report is identified by the final GitHub permalink and local
delivery receipt, rather than a self-referential hash inside its own contents.

| Phase | Commit | Evidence |
| --- | --- | --- |
| Startup scope, source attribution, rescoring and table diagnostics | `d54ba838ca56d7bf2ecbcd4b6634675bce940397` | 138 offline unit tests passed |
| Persistent campaign paths, indexes, conflict/recovery/archival | `0a13c98a6d4ae6876dbe3ff00c4247c4abee692b` | 15 targeted regressions passed |
| Provider/history/Judge mock-capable paths and final corrections | `d045a9e8922d2d42461e6dd3c3c31e617fc409c4` | Final evidence below |
| Artifact alias metadata and nested-index completeness | `ae38449179d17f093896accb937c9e143769650d`, then `1ba9d339520ffa7956375a3330676851790a02db` | Four artifact regressions passed after each scoped change |

Restore the previous version without rewriting history or discarding new work:

```bash
git status --short
# Inspect and separately preserve any new edits before switching.
git switch -c restore/pre-api-preparation-20261025 backup/dynamic-api-preparation-20261025T130058Z
git rev-parse HEAD
# 37226afc4d8b94b5895cb32918f5345d76ec6e95
```

For a clean separate checkout, use `git worktree add --detach "$RESTORE_PATH"
37226afc4d8b94b5895cb32918f5345d76ec6e95` with a new empty path. The backup tag is
local; the starting commit is also reachable in the repair branch history. No
hard reset, force push, main merge, file migration, VHDX deletion, data cleanup or
issue mutation is part of this delivery.

## Repairs and boundaries

| Item | Change and evidence contract | Remaining boundary |
| --- | --- | --- |
| R1 | `Scheduler.protects_delegation` uses actor, invocation, stage/epoch and open slice. The same query is used by coordination and `Delegations.update/cancel`, including checkpoint restore. After closure, queued work follows normal update/cancel rules; started/terminal work returns ordinary state errors. | No new cancellation powers, global barrier, extended slice or team serialization. Four initial requests remain unchanged. |
| R2 | `build_visibility_index` corroborates invocation/delegation lineage and the producing Main request. Runtime startup, initial plan, voluntary Main handoff, peer and unknown sources are distinct. Queued-only work is not exposure; repeated actual inputs remain separate; submitted and successful response states remain distinct. | Missing/ambiguous lineage is unknown, not inferred from text or labels. Existing voluntary-use and extra-character exclusion is preserved. |
| R3 | Explicit `rescore_dynamic` retains original run/manifest/events/exports/bindings and original scorer. A new version records parent, reason, annotation provenance, origin/current hashes, raw evidence and Judge requests. Complete staging precedes publication; the current pointer is updated last. Default scoring stays strict. | Old annotations are not re-labelled as new. Pending is the default. Reuse requires unchanged Judge semantics and explicit compatibility; a new sidecar is explicit. Corrupt evidence fails without replacing the old current version. |
| R4 | Table 3 now exports counterevidence opportunity and correction diagnostics with applicable/judged/missing counts and existing coverage rules. No opportunity or absent annotation is not failure/zero. Existing partial RTF/RSR keeps formal value null and subset value diagnostic only. | No change to the eight anchors, polarity, confirmation family, research hypotheses or five-table meanings. |

Ten new startup/source/table-export regressions fail against the actual baseline
modules loaded in memory, and pass with the repair. No old checkout or saved run
was edited to manufacture those failures. Formal scorer lineage has separate
strict/default and explicit-rescore unit tests; real Pi/Docker integration
creates a synthetic frozen run, changes scorer version, preserves old outputs
and rejects archive tampering. Synthetic provenance is never promoted to formal.

New versions seal complete event envelopes, including timestamps omitted from
the public Judge view, and workspace plus additional service archives. A legacy
version without this seal requires a retained original event-byte audit through
`--source-audit`, and original run bytes must be recoverable from its immutable
summary or explicitly audited. Missing provenance stays
`rescore_source_seal_unknown`; this repair does not invent original hashes by
rehashing potentially changed files today. Annotation reuse also requires the
parent's exact original annotation hash and scorer, not just compatible recent
scorer code.

## Provider, history and Judge code

`provider_adapter.ts` uses the installed Pi 0.84.1 completion adapter's actual
types, payload conversion, stream parser and tool loop. Its custom fetch relays
only method/URL/body to `ProviderTransport`; no credential or SDK authentication
header crosses the RPC boundary. `io_guard.ts` retains its host task filesystem,
process and deny-all bridge network traps. Provider outbound is a distinct host
transport, not permission for task tools to execute on the host.

Modes are explicit. Scripted stays scripted; mock requires an injected local
transport and remains synthetic. API requires explicit mode, enabled local flag,
per-run authorization, exact provider/base URL/model/key-env/API/compatibility,
supported temperature/output mapping, verified route capacity and independent
cost/rate/request limits. Missing fields stop execution; no model inference,
fallback, credential-triggered activation or silent truncation exists. The
planned temperature is 0.2; unspecified sampling/thinking parameters are not
added by this layer. SDK retries are disabled. Host attempts, provider request
ID, raw returned body, errors, partial/unknown outcomes and reported usage are
recorded locally. Unknown prices/cost/usage are not provider zeroes. Missing
output usage conservatively charges the existing output reservation and records
that distinction.

`run_dynamic` now has explicit mock/API paths and new binding/authorization/
request-ceiling/mock-response/campaign options. The prior CLI supported only
scripted mode; this report does not retroactively claim otherwise. No API path
was executed against an external provider in this repair.

`history_execution.py` runs H1/H2 through the same `PiDynamic`, original task
loader, Docker deployment, normal goals, stages, sessions and scheduler. Initial
and terminal exports are independent. Each history record includes source task,
bindings, status, budget/request hashes and actor session hashes; T3 records its
history bundle ID. Fresh tasks receive no previous workspace or service. Only
Main/A/B carry their own allowed sessions, subject to original stage resets;
C/D receive none. Failed/refused/budget-ended histories are retained rather than
selected for success. A failure without a complete carry state remains blocked,
not an invented successful history. The 20 newcomer portfolio entries remain
synthetic regardless of H1/H2 backend.

`judge_client.py` and `judge_dynamic` are separate from pure scoring. They send
the exact prepared wire payload, bind hashes, maintain independent Judge limits,
validate response and trajectory anchors, formal delivery IDs, JSON and evidence
references, and create a new annotation sidecar. Optional semantic goal inputs
use the original GoalSpec and versioned annotation contract. Scoring recomputes
the request from the same frozen view/rubric/format/budget before consuming that
sidecar. Predicates and semantic judgments remain separate; absent labels stay
unknown. A queue acknowledgment is not a formal answer. Judge failure does not
rerun the team.

API code is implemented and mock-tested; live provider compatibility, live
history, real Judge behavior, unknown pricing/usage cases and operational recovery
under actual service failures are not claimed verified. Streaming HTTP is
buffered at the host relay; partial response text and interrupted outcomes are retained,
and no automatic side-effect replay is implemented. Incomplete attempts require
reconciliation, not a silent restart.

Implemented transport scope is OpenAI-compatible completions. Other API shapes
are rejected. The live capacity guard currently implements only the existing
local `o200k_base` counter; its applicability must be verified for each exact
route. A different tokenizer, including any required by the official DeepSeek
route, needs a locally available, validated implementation before sending. No
approximate substitution is approved. Multimodal message accounting is likewise
blocked when unverified; images are not dropped to make a request fit. Generic
automatic recovery of a partially executed API attempt is not implemented; the
existing checkpoint contract and explicit reconciliation remain the boundary.

## Validation and issue #1

Final checks on the implemented code:

- **156 unit tests passed**, no failure/error/skip; `test-results/final-units.xml`.
- **41 unique Pi/Docker integration cases have passing records**: 33 retained
  passes from the interrupted comprehensive run, then eight failed/unexecuted
  cases passed in the focused continuation. The collected node-ID set exactly
  equals their union; `integration-coverage.json` records both JUnit hashes and
  the fixture-only correction. This is **not** claimed as one uninterrupted
  41-case green invocation. The interrupted failure is retained.
- The new H1/H2→T3→mock Judge CLI→new annotation rescoring path, invalid tool
  validation before remote work, and frozen cross-scorer integrity path also
  passed their separate three-case targeted run. C/D first inputs contained no
  inherited old sessions; task files did not carry across H1/H2.
- Node typecheck exited 0; **10 Node contract tests passed**, no skip. They cover
  SDK conversion/tool continuation, 429 without retry, timeout, truncation,
  partial stream, malformed tool JSON, exact bindings, host IO traps and the
  original per-file queue's independent-file concurrency.
- All 14 continuation/diagnostic/help commands exited 0. Offline preflight,
  provider metadata preflight, frozen plan generation, retained-input capacity
  audit, five CLI `--help` commands and `git diff --check` completed. The plan
  remains 1664 branches; no formal matrix was executed.
- The new campaign CLI example completed one scripted p001/S/HP block and index
  verification. A second invocation against that same output was rejected before
  starting another block. This is an engineering fixture, not a formal trial.
- Final indexing encountered pytest's actual `current` symlinks. The index now
  hashes link target metadata without following targets, verifies alias changes,
  and includes nested index files while excluding its own active index. Four
  focused artifact tests passed after this metadata-only follow-up; the full
  156-unit and 41-case execution checks above preceded it. These counts are not
  added as if the three repeated artifact tests were new independent tests.

Initial failures are retained: early unit tests exposed a changed synthetic
rejection order and outdated startup test setup; those were fixed. The first
history integration correctly rejected export before freeze. A second failure
was in the mock: it treated old task tool messages as evidence of current task
work; the mock now keys its marker to the current task. Neither fix changed the
research protocol or disabled an isolation check.

The first comprehensive integration pass was stopped after 15 passes and three
L-path assertion failures. Behavior had completed; the old test expected a zero
summary while the new raw summary temporarily used null. The implementation now
derives those summary counts from actual request events, preserving the old
interface without restoring hardcoded zeros. The interrupted run is not counted
as a complete acceptance.

The subsequent comprehensive run reached 33 passes and one old fixture failure:
it compared the entire startup dictionary to the previous two-field shape. The
fixture now binds the actual invocation and explicitly checks four requests,
closure reason and invocation ID; its six-turn continuation assertions remain.
Only that failed case and the unexecuted remainder were rerun. No runtime rule
was weakened, and no unrelated passed case was repeated to inflate the count.

Issue #1 was read through the GitHub connector and remained open with zero
comments. This repair sends no issue comment and does not close it. The capacity
audit reuses the actual retained ten original scoring inputs and an explicitly
synthetic six-stage fixture; it does not regenerate behavior to reproduce old
numbers. It counts decoded message contents and local tool/response schemas,
including rubric/format/codec instructions. Wire JSON escaping is separate.

All ten original views and the explicit long fixture retained their decoded
hashes and passed exact lossless roundtrip. With the same legacy audit format as
the prior report, the ten full input estimates remain **95597–187331 tokens**
before encoding and **44751–91879** after encoding. Five of ten legacy candidates
exceed the illustrative 128000 context when adding the diagnostic 4096 reserve;
all ten encoded candidates fit that reference, assuming zero additional framing.

The new sender has a more explicit JSON output-format instruction than that
legacy audit. Its system message is exactly **87 tokens larger** under the same
cached tokenizer for each representation. The unchanged user-message hashes and
counts plus this exact system-message substitution give:

| Retained inputs | Legacy-format full / lossless input | Current sender format, full / lossless input |
| --- | ---: | ---: |
| p001, four conditions | 95597–96538 / 44751–45763 | 95684–96625 / 44838–45850 |
| p006 primary | 98170 / 48475 | 98257 / 48562 |
| p006 r70 | 129266 / 57866 | 129353 / 57953 |
| p024, four conditions | 185573–187331 / 90431–91879 | 185660–187418 / 90518–91966 |
| Synthetic six-stage fixture | 5809683 / 19366 | 5809770 / 19453 |

The current-format column is an exact local message-content projection, not a
request that was sent or server usage. The optional GoalSpec/annotation-schema
variant is not included in this projection; the actual sender prepares and
preflights that full variant separately. Tools/schema, format and representation
content are counted when included; no wire-escaping count substitutes for model
text. Detailed input hashes, tokenizers and calculations remain in the local
`issue-comparison.json` and `current-sender-format-capacity.json` diagnostics.

The illustrative 128000 context / 4096 reserve comparison is not the effective
third-party route or an approved Judge output budget. Actual route/tokenizer/
framing/capacity/budget remain unknown where not evidenced. Lossless roundtrip
does not prove LLM scoring equivalence. If the complete representation still
exceeds a verified route, the sender blocks with diagnostics; it does not crop,
average chunks, switch Judge or shrink the experiment.

Suggested issue update for the user to publish, if desired:

> The repair branch now has offline-tested exact Judge request preparation,
> route-bound capacity gates, lossless trajectory encoding/roundtrip, immutable
> frozen-run rescoring and separate mock-capable provider/Judge transports. The
> retained original inputs were re-audited; see this engineering report for
> corrected decoded-content estimates. Real provider/Judge calls remain disabled.
> Effective third-party capacity, tokenizer/framing, independent Judge budget and
> real legacy-versus-lossless scoring equivalence still require an explicitly
> authorized live validation phase. Please keep this issue open.

## Persistent evidence and actual calls

See [Run artifacts and logging](Run_Artifacts_And_Logging.md). Local evidence is
primarily identified by campaign `api-preparation-final-20261025`:
`acceptance-resume-v2/commands.json`, `test-results/`, `diagnostics/`, saved mock
histories, immutable scoring versions and `artifact-index.json`. Early evidence
remains in `api-preparation-20261025`; the separately verified CLI fixture is
`api-preparation-cli-smoke-20261025`. The final call audit covers all three.
The actual absolute machine directory and storage
evidence are supplied only in the local report and user reply, not in Git.

The code and native Docker store were verified on Linux ext4. The registered
Windows path initially appeared to be on the system drive, but reparse-point
inspection found a junction into the data drive; both VHDX paths return the same
Windows file ID. The target directory and its parent have no further reparse
point. Thus the active Ubuntu VHDX and native Docker bytes are on the data drive,
not inferred from names or sizes. New large trajectories, JUnit and engineering
logs also use the audited persistent data-drive directory. Existing code, Docker
root, WSL registration, VHDX files and caches were not relocated. The initial
registry-only drive inference was corrected. A frozen initial snapshot does not claim
a RAM checkpoint. Existing audited Docker images and tokenizer/dependency caches
were reused; no unrelated harness or dependency installation was performed.

The early campaign used the Windows-mounted data directory. After the junction
was verified, final high-frequency tests used a new persistent ext4 directory
within the same data-drive-backed Ubuntu. Early logs were not moved or erased.

The active endpoint is the local Unix Docker socket and the Ubuntu Docker service
is active. Its native `dockerd` executable and data-root device/inode match the
inspected Ubuntu directory; daemon configuration uses the default data root.
These checks distinguish the active native daemon from an unused Desktop disk.

The final retained-log audit found:

| Current-round evidence | Observed count |
| --- | ---: |
| Actual model-input submissions in scoped bridge ledgers | 509 |
| Submissions with explicit scripted/mock provenance | 509 |
| Explicit API-backend / unresolved-backend submissions | 0 / 0 |
| Host HTTP mock attempts, a separate overlapping layer | 128 |
| **Real model requests / real Judge requests** | **0 / 0** |
| Unfinished scripted attempts retained from interruptions | 2 |
| Unique guard RPC receipts | 979 |
| Positive bridge network / host-IO-violation receipts | 0 / 0 |
| Audit read errors / HTTP source conflicts | 0 / 0 |
| Complete historical model/Judge totals across the prior gap | UNKNOWN / UNKNOWN |

The two unfinished attempts have explicit scripted provenance, not evidence of
an API request. Independent component tests can reuse a fixture branch ID, so
the audit retains the original references with their actual ledger source
scope; it does not conflate different tests or count shared prefix JSON copies
as new originating ledgers. HTTP mock attempts and bridge submissions must not
be summed. Initialized guard counters and run-level fixed zeros were not used
as proof. The artifact-index follow-up ran only filesystem metadata unit tests
and created no additional model/Judge traffic.

This campaign retains persistent raw evidence, including failed tests. The prior
repair's known early temporary-log gap is still a historical gap: complete
historical model/Judge totals remain UNKNOWN. Present-scope observed counts and
missing history are reported separately; later reruns cannot backfill it. Keys
remain only in local configuration/environment and are excluded from code,
public reports and Git.

## Next authorized phase: exact prerequisites and command templates

This section is a future template, not authorization or a record of live runs.
First inspect without credential reads or requests:

```bash
python -m trustfork.tools.provider_preflight --bindings "$BINDINGS" \
  --out "$CAMPAIGN/diagnostics/provider-preflight.json"
python -m trustfork.tools.run_dynamic --help
python -m trustfork.tools.judge_dynamic --help
```

Unresolved protocol/configuration fields must be explicitly supplied and backed
by evidence: exact `provider`, `base_url`, `model_id`, `key_env`, completion API,
per-route compatibility flags, supported parameters/output mapping; effective
context/output capacity, tokenizer/version/count method/applicable route,
framing, source/evidence/verification date; independent Judge output budget;
and separate model/Judge `execution_limits` with request/cost/RPM/TPM ceilings
and exact route/model input/output prices. No Flash alias expansion or official
specification is substituted for third-party evidence. No context compaction
strategy has been approved or added.

The actual local preflight found provider/base URL/model/key-environment identity
fields populated without reading key values. For **both aliases**, the remaining
binding fields are `context_window`, `max_output_tokens`, `supported_parameters`,
`api`, `compat`, `output_token_parameter`, plus effective-capacity/tokenizer/
framing evidence. `execution_limits` is not configured; the independent actual
Judge output budget remains unset. Preflight exits successfully as an offline
inspection while explicitly reporting these unresolved fields; it does not mean
the API sender is ready.

After explicit new authorization, complete local settings and live preflight,
a one-condition discovery smoke template is:

```bash
python -m trustfork.tools.run_dynamic --mode api --bindings "$BINDINGS" \
  --allow-real-api --request-ceiling 360 --case p001 --protocol S --conditions HP \
  --trial-workers 1 --out "$NEW_SMOKE_BLOCK"
python -m trustfork.tools.judge_dynamic --mode api --bindings "$BINDINGS" \
  --allow-real-api --request-ceiling 2 --run "$RUN/run.json" \
  --judge-output-budget "$APPROVED_JUDGE_OUTPUT" --out "$NEW_JUDGE_ATTEMPT"
```

The first ceiling bounds provider attempts across H1/H2 and one T3 branch:
120 + 120 + 120, with the shared prefix already included in the T3 budget. It is
a worst-case guard, not an expected count or a requirement to exhaust it. Team
output is at most 3 × 48000 for those three tasks; each attempt still respects
4096 and each original stage retains its time limit. Judge has two separately
budgeted passes and no team rerun on failure. Input tokens, actual usage and
prices are not yet known, so a numerical dollar estimate would be invented.
The cost guard reserves `(input_tokens × input_price + output_reserve ×
output_price) / 1e6` against the explicit route budget before each request. It
does not assume cache discounts. Neither 1664 branches nor 1712 planning items
are model-call counts.

Formal readiness remains false until real H1/H2, provider/tool/error behavior,
Judge capacity/output/annotation links, the real full-versus-lossless discovery
comparison and relevant case evidence have actually passed. The 24 semantic
goal labels, original recipient/use interpretations, source-card independence
and any future compression/research decisions are not invented by this repair.
