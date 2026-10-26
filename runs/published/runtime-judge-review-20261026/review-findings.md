# Runtime / Judge review findings

Baseline d68a3a871adcd16688d66b5ec39a67de977176f9. All old raw failures remain unchanged.

| Problem | Confirmed cause | Change | Evidence / remaining limit |
|---|---|---|---|
| Coordination | No explicit wait; every toolUse requeued Main. Directory is membership only. | Versioned wait/work-status tools, atomic check/register and observable wake, shared outcome, checkpoint waiting/deadlines. | Unit races, final multi-tool priority, timeout/exit/deadline; Docker wait→worker delivery→freeze/exposure→Judge. Models can still choose to poll. |
| Judge consumption | Prompt field domains were incomplete; consumption ran after repair; sanitized views lack original scoped receipt metadata. | Shared field/complete validator; frozen raw validation context hashed before HTTP; errors carry paths/domains. | Four original answers rejected; alias changes are diagnostic only and still fail lineage. No alias guessing or oracle feedback. |
| Formal facts | Blocked unsafe attempt expected5 instead of rubric3; checks omitted safety/utility. | Frozen V2 fixtures: terminal3→TH40, explicit utility, unknown response, visible/no opportunity, formal/refusal/queued response. | Fact mutation and same production validator; offline is synthetic, actual acceptance separate. |
| Truncation | length with empty content was sent to structural JSON repair. | Separate bounded length calibration and at most one structural repair; original answers/reasoning retained. | No calibration/repair recursion; 65536 trajectory /16384 response targets, optional131072 explicit calibration. Real gate can still fail. |
| Audit resources | Repeated full partial snapshots plus unbounded bridge inputs/events, Python rows, exporter shards. | Disk authority/index/bounded cache, per-turn bridge retention, ordered durable FIFO/backpressure, immediate lossless shard packing. | Original762MB replay and real Pi120-turn incremental SSE mock, disk-write fault tails, input/hash/order equality. Legitimate conversation still grows. WSL exit root cause UNKNOWN. |
| Continuation | Code/config identity was tied to old budget bucket; completed stages and new transports collided with journals; clone exposed half-copies. | Separate versioned attempt + original100/20 budget; durable per-stage reuse/reconcile; atomic verified clones; append-only transport relay journals included in review. | Same SQLite migration copy, unknown charges, crash after history/prefix/HP, protocol incompatibility, no resampling. No HTTP response fabricated into checkpoint. |

## Audit corrections and limits

Read-only original H2 contains Main70 replies (67 toolUse,3stop), A26,B24; 57 directory-only Main calls are47.5% of all120 calls. The supplied document's66 is not the full Main reply count; its intended subset remains UNKNOWN.

A compileall command accidentally created task-environment bytecode caches. All3465 files (191641716bytes) were copied and hash-verified locally before deleting only those generated outputs; all30 original case asset hashes were restored. No .py source was altered. Backup and exact remediation receipt remain local; only sanitized receipt is published.

The temporary worktree's first full unit run had365 passed/1failed because it lacked the existing pinned tokenizer cache. Existing dependencies were linked without installation; final committed run has367 passed. All red/initial failed logs remain. Earlier dirty/untracked red fixtures are not evidence of the baseline commit passing/failing unchanged; later clean committed acceptance is authoritative.

## Additional actual-run finding and offline repair

The first trajectory answer marks an externally blocked action effect_status=observed while its own reason says failure/unchanged. Two fact assertions failed; no factual resampling or oracle weakening. Response formal gate passed.

Old F/HA response strict pass completed, then metrics consumption failed: the consumer reconstructed the new DeepSeek request using the frozen old GPT Judge binding. A public versioned/hash-checked scoring binding snapshot now accompanies new sidecars; the consumer uses that actual scoring binding and still rejects tampering. Legacy frozen manifests and paid sidecars are untouched. Actual paid-answer mock replay passed, portable cross-route chain and two existing scoring Docker integrations passed, and committed unit suite368 passed. This post-paid fix has NOT been truly revalidated.
