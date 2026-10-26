# Offline acceptance evidence

Final: Python unit 254 passed; all integration tests partitioned into a/b/c, 24+9+20=53 passed; Node/Pi 11 passed; TypeScript no diagnostics and exit 0. The final runtime file repeats four integration cases after additive diagnostic changes; it does not add four unique cases.

Commands: existing Python -m pytest tests/dynamic/unit -q; integration groups use the same pytest command, with TIKTOKEN_CACHE_DIR=$PWD/build/dynamic/api-config-audit/tokenizer-cache and TRUSTFORK_ARTIFACT_ROOT set to the audited existing location. Exact group file lists are retained in offline-acceptance.json. Node: node --test tests/*.test.ts; TypeScript: ./node_modules/.bin/tsc --noEmit from trustfork/runtime/dynamic.

integration.txt is an earlier interrupted attempt (30 passed,6 failed), which omitted the existing tokenizer-cache environment and initially used old mock output limits. failure-focus.txt and homogeneous-rerun.txt retain diagnostic failures. They are superseded by the final accepted files, not hidden. No tokenizer download/install was used.

Every provider response during these tests was scripted or mock. A configured key did not authorize any of these tests to select a real sender.

Post-run publication code: 258 unit tests passed, including nine export/packing tests. The recorded publication-initial-path-failure.txt is a superseded regression caught before any export was published. The experiment execution acceptance remains its original 254 unit tests at the fixed execution SHA.

Final privacy follow-up: 259 complete unit tests passed, including ten publication cases. A local pre-upload scan rejected dictionary-key personal paths in the first unpublished draft; mapping keys and redaction references were fixed and the full copy re-exported. No model/Judge request was made during publication work.
