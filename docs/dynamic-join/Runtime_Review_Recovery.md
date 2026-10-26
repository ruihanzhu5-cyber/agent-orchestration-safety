# Reviewed runtime / Judge recovery

This interface uses the original `first-api-20261026` CNY100 ledger and its existing `plan-judge-followup-20261026` CNY20 segment. Execution attempts carry new code/config/protocol/scorer identities; they do not create more money. Default local bindings remain offline. The original stopped S prefix has no checkpoint and remains interrupted.

The reviewed coordination interface is `explicit-wait-v1`. `get_team_directory` remains a membership query. `get_work_status` returns actual delegation states and the caller's visible coordination version. The caller can explicitly select `wait_for_update(after_version, timeout_seconds)`; only a successful last tool in the turn registers a wait. Later tools override it. A parked actor releases its permit; visible updates or a deadline wake it without creating exposure. Exposure still requires the subsequent actual frozen input. Independent checkpoint forks preserve remaining wait duration; an ordinary restart respects the elapsed wall deadline.

With the existing environment and artifact root, inspection does not load credentials or send a request:

~~~bash
python -m trustfork.tools.runtime_judge_review inspect \
  --parent "$TRUSTFORK_ARTIFACT_ROOT/campaigns/first-api-20261026"
~~~

`reconcile` also has no sender. It requires a complete typed artifact and the recorded stage identity. It verifies actor-scoped history sessions and the exact ledger, checkpoint/source identity, a complete frozen run, or an already validated independent Judge pass. Missing/incomplete artifacts remain blocked. An HTTP response alone never qualifies. Example for a new attempt's complete raw prefix checkpoint:

~~~bash
python -m trustfork.tools.runtime_judge_review reconcile \
  --parent "$TRUSTFORK_ARTIFACT_ROOT/campaigns/first-api-20261026" \
  --out "$REVIEW_ATTEMPT" --attempt-id "$REVIEW_ATTEMPT_ID" \
  --stage prefix/S --kind prefix \
  --artifact "$REVIEW_ATTEMPT/deepseek/blocks/S/prefix/checkpoint.json"
~~~

Paid `resume` requires explicit `--allow-real-api`, a clean committed source tree, and a passing `offline-acceptance.json` at the attempt's parent with the exact execution SHA. It freezes its plan/config before loading the existing local credential, backs up and applies the tested association migration if necessary, then executes only the fixed review plan. No other matrix or seed is scheduled.

~~~bash
python -m trustfork.tools.runtime_judge_review resume \
  --parent "$TRUSTFORK_ARTIFACT_ROOT/campaigns/first-api-20261026" \
  --out "$REVIEW_ATTEMPT" --attempt-id "$REVIEW_ATTEMPT_ID" \
  --bindings .env.dynamic-bindings.json --env-file .env --allow-real-api
~~~

The predeclared formal plan contains three trajectory fixtures paired across v1/v2, two response fixtures, and one queued-only program check. The eight scoring candidates use the same explicit output reserves as their target passes: trajectory 65536, response 16384. The only optional length calibration reserves 131072 after an actual length result, with a fresh request/hash, full preflight and fee reservation. Each pass has at most one initial send, one length calibration and one structural repair; these operations do not recurse. The formal group has a shared atomic 24-request cap. Fixed new history, prefix and T3 generations cannot be sampled again under a new attempt ID. Compatible completed parent histories, including budget-ended ones, may be inherited after exact artifact/contract checks.

The old four GPT teams are never rerun. Their behavior and new scoring identities stay separate. Each independent score pass and each metrics publication is persisted before continuing. Known shared scoring failures suspend their dependent paths. A failed/blocked stage is retained; changing directories or changing code does not erase its requests, unknown fees, or parent lineage. A different source/config requires a new attempt, still inside the original bucket and the review's fixed generation limits.

All offline fixtures and metrics are synthetic. A full schema/consumption check is shared by production and formal fixtures; original frozen event context is required for real tool-receipt scope, and its source hash is checked before HTTP. No alias rewriting, guessed IDs, response normalization, missing-score zeros, event deletion, or history summarization is used. The new interface is a coordination protocol change and does not make new DeepSeek runs strictly comparable to old GPT runs.
