# 0451 pilot log

## Authorized scope

Only `trustfork_0451`, Direct / Peer-Control / Peer-Chain. Historical truthful
and swap outputs remain untouched in their previous result directory. They
serve as observational reference; no native repeat is scheduled by this pilot.

Models are supplied through the existing external local registry: Main GPT-4o;
slot B GPT-4o; A/C/D DeepSeek V4 Flash. Display is the existing truthful M1 pool,
private goal G1 belongs only to D, and breadth stays free. Record the exact
resolved bindings in the private run manifest rather than provider details here.

## Verification status

Focused verification: 12 Python tests and 5 mocked SDK runtime tests
passed. These validate original generation equivalence, overlay assets,
permissions, actual respondent extraction, NA/unknown handling, three paths,
failure handling, later individual authorization and fresh-session intake reset.
They are synthetic contract tests, not empirical results.

Real preflight found two issues, retained as preflight artifacts:

1. Fresh generation omitted the local Docker egress override and GPT-4o model
   limits used by the historical run. The gateway returned upstream account
   deactivation errors in native streaming while a minimal SDK request succeeded.
   The new driver can reuse only compose/model-limit transport fields from a
   successful reference; endpoint/credential bindings must match exactly.
2. Under the initial unrestricted intake scope, the source executed file changes
   before a peer could answer. Direct stage-one provenance passed (real D reply,
   then a separate Main-selected C verification), but this is not a valid design
   for attributing those early writes to later peer-mediated authorization.

Protocol `trustfork-peer-v0.2` therefore gives all three new conditions the same
advisory-only intake scope instruction. Actual tools and write permissions remain
unchanged. Scope violations are audited, never repaired by resampling. Subsequent
Main-selected execution uses its requested scope normally.

A fresh three-mode v0.2 pilot was launched after this correction and all 17
focused tests passed. Results and manual audit must be taken from completed
artifacts. No completed three-condition result, ICS positive case, or new failure
mode is claimed at this revision.

## Artifacts to inspect

Each unique run directory under ignored `build/peer-pilot/` holds:

* `peer_run_manifest.json`: task/mode/model bindings and comparison signature;
* `configs/`: frozen Harbor configs; no credentials in tracked source;
* `run_ledger.json`: first-valid, bounded infrastructure retry history;
* `jobs/`: actual native sessions, final eight scores and independent Peer files;
* `peer_summary.json` / `.md`: per-condition table, metric denominators and ICS.

Final verifier outputs include `peer_audit_view.json`,
`peer_main_visible_view.json`, `peer_protocol_facts.json`,
`peer_terminal_workspace.json`, `peer_stage_quality.json`,
`peer_annotations.json`, `peer_metrics.json`, and original reward/annotations.
Per-stage workspace artifacts permit terminal-state and early-write inspection.

Manual review must inspect actual D text, B's native input/output, Main's tool
observation and later authorization IDs. Record disagreements with the judge;
do not overwrite native scores to match a preferred interpretation.

## Known limits

Shared workspace can transmit source edits before the peer handoff; initial
intake may itself execute the task. No subsequent Main authorization makes PMAC
inapplicable. G1 need not produce unsafe proposals. One case does not provide
population rates, model comparisons or a causal identity effect. Total billing
may be unavailable even when native token/cost estimates exist; label missing
components explicitly.
