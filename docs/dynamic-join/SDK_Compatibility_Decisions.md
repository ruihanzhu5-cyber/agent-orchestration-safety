# v9 implementation compatibility decisions

These are observed implementation constraints, not new research settings. The
SDK patch below was explicitly authorized by the user on 2026-10-24. Its
acceptance still requires the real-Docker/SDK regression tests described below.

## Pi 0.84.1 grep remote execution

The installed `dist/core/tools/grep.js` has SHA-256
`15485f75d1ff037ab7c2b2be9cb38684deaf129356f4df1250e800d8a0b555dd`.
Its public GrepOperations exposes only isDirectory/readFile. Line 99 calls
ensureTool('rg', true) and line 148 directly calls child_process.spawn even
when custom Operations are provided. The real-SDK negative probe
`trustfork/runtime/dynamic/tests/grep-contract-probe.mjs` exited 1:
`BLOCKED_HOST_EXEC_WITH_CUSTOM_OPERATIONS`; one local rg spawn was trapped,
with zero model, judge or network requests. No local search was executed.

Implementation instructions section 5.3 explicitly requires stopping at an
interface that cannot support isolation. Unmodified production startup must
therefore reject the seven-tool dynamic runtime; silently removing grep or
running its search on the host is not an alternative.

Authorized minimal, version/hash locked dependency patch:

1. Add an optional public `spawn(args)` transport callback to GrepOperations,
   returning the stdout/stderr/event/kill surface used by the existing code.
2. When that callback is present, skip local ensureTool and route only process
   creation through it. All existing argument construction, JSON match parsing,
   limit cancellation, context handling, truncation and errors remain in Pi.
3. When absent, preserve original behavior. Dynamic mode always requires the
   remote callback and a final-registry/local-execution trap.
4. Send rg operations only to the task container through the host RPC. Record
   the original SDK hash and exact patch hash; keep version 0.84.1 explicit.
5. Test multiple matches, limit truncation, context, errors, cancellation and
   a strict host fs/process trap before enabling this path.

The user authorized this interface extension, required repository reproduction,
version/hash locking, preserved search semantics and tests proving no host search
or failure fallback. The patch is confined to the local project dependency.

## Requested original memory/new_session test

All five canonical original memory cases are single-stage with new_session=false:
p005, p027, p028, p029 and p030. Each has one stage named ask. The specified
p028 source is `trustfork/tasks/memory/trustfork_1702`.
There is no alternative within the existing memory case list satisfying the
instruction's original multi-stage memory requirement. The original p024 chain
case (`trustfork/tasks/chain/trustfork_1450`) has three stages, the final one
with new_session=true.

Accepted coverage: retain the required original p028 memory test unchanged,
and test real new_session transitions separately using original p024 chain.
This changes only the impossible test-coverage requirement, with no new stages,
case substitution in the research matrix, modified assets or research setting.
The user explicitly accepted separate coverage. The report must identify the two
different original cases and their unchanged stage/new_session fields.

## Package document-reference discrepancy

All ten files match file_hashes.json. The actual project-plan SHA-256 is
541276f5fcc76ed07afb6d3350dce88fabda551ec6bd55b921ff3072512fc6f2.
The implementation document's embedded reference is the older
b3bb0f559db9e61a08f426af28439746bc7051c3a958d9ed394af228578b715a.
Original documents are preserved byte-for-byte; source_lock.json records both.
