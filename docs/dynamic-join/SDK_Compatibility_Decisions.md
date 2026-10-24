# v9 implementation compatibility decisions

These are observed implementation constraints, not new research settings. The
user authorized Docker-only tool path repairs. Real SDK/Docker regression tests
and an independent offline installation now substantiate the implementation.

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

## Accepted read and mutation-queue path repairs

Two subsequent real-SDK traps identified host reads before remote Operations:
read's asynchronous path-variant resolver used host fs.access, and write/edit's
shared mutation queue used host realpath. The user separately authorized an
optional remote existence callback and optional queue canonicalization callback.
The queue algorithm remains Pi's per-file queue: aliases serialize while other
files run concurrently. No global operation queue was introduced.

All calls use Docker operations, including F_OK versus R_OK checks. Container-only,
host-only, nonexistent and same-path/different-content tests prove the active
namespace. No fallback to host IO is permitted. Image detection operates on
remotely read bytes; Pi's image processing, path-variant order, read/write/edit
validation, truncation and errors are preserved.

## Native find transport and pinned fd

The public glob callback bypasses native fd behavior. An initial rg-based
implementation omitted empty directories. Under the user's authorization to
repair all tool paths while preserving behavior, find now uses the same optional
remote spawn pattern as grep, and its .git ancestor checks use remote exists.
Native fd arguments, parsing, directory suffixes, limit notices and errors stay
in the original Pi function. Defaults are unchanged when callbacks are absent.

The base image has rg but no fd. The explicit dependency command installs fixed
fd 10.3.0 from its official release; archive and binary hashes are locked in
runtime-dependencies.lock.json. Runs never download it and fail on missing or
changed bytes. Only the public binary is copied into a task. Official source:
[fd v10.3.0](https://github.com/sharkdp/fd/releases/tag/v10.3.0).

The project lock covers 14 SDK files (implementations and declarations).
`npm ci --offline` in an independent directory reproduced them; repeated apply
was idempotent; altered versions and file bytes were rejected. Every corresponding
file in the original independent Pi installation still matches its original hash.
Real-Docker oracle comparisons use the unmodified Pi factory inside the task:
grep matches/context/limits/errors and find empty directories/path globs/gitignore/
limits/errors agree. Bash retains Pi tail truncation and exposes its full output
inside the task. Real SDK tests prove one complete batch per host permit, and
goals/resources survive restore, reload and explicit synthetic compaction.

Pi deliberately omits skill directories for actors without the read tool. Main
has no work tools; Sub resource tests therefore use a Sub, preserving this native
SDK rule. An empty conversation may already have model/configuration entries and
a leaf ID; emptiness is not inferred from a missing session file or null leaf.
