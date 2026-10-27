# Small API experiment — 2026-10-27

Four new DeepSeek T3 behaviors completed and frozen; old GPT behavior is rescored only. Main/A/B/C/D bindings and original p001/p002/p007 tasks are retained. The primary behavior matrix has one sample per cell. Two additional infrastructure-failed partial T3 attempts are disclosed separately.

## Read in this order

1. [Experiment report](../../../docs/dynamic-join/Small_API_Collection_Report_20261027.md).
2. [Four behavior rows](behavior-results.csv), [inherited core metrics](core-metrics.csv), [calibration reliability](extended-metrics.csv).
3. [Actual request accounting](accounting.json) and [per-request costs](costs.csv).
4. Evidence for each result: `scoring/new-*` and `scoring/old-gpt-*`; complete selected execution exchanges under `logs/`.
5. [Fault decisions](diagnostics/decisions.json), [engineering attempts](diagnostics/engineering-attempts.json), [validation](validation/README.md), [source index](source-index.json).

## Score interpretation

RTF/RSR/TH/TUL retain the original TrustFork scales and formulas, adapted to actual formal deliveries. Higher values indicate worse failure. A partial subset diagnostic is not a complete primary score. Null, unknown, not annotated, not applicable and numeric zero differ. TH/TUL remain not annotated because the independent trajectory calibration failed; no semantic resampling was used to make it pass. Calibration fixtures are not research samples. One case and one repeat per cell do not support significance, general ASR, high-versus-medium reputation claims or model-superiority claims.

## Log selection

This directory contains the evidence needed to audit the results, not every temporary file. Compressed JSONL files are ordinary gzip. Complete final model exchanges, tool results, action/message records and score inputs/outputs are preserved. Repeated token-stream fragments, duplicate snapshots, temporary scoring copies and repeated test output are excluded from GitHub. Complete originals remain local and are indexed by source hashes. Unknown-charge requests remain held in the original ledger; supplier invoices are UNKNOWN.
