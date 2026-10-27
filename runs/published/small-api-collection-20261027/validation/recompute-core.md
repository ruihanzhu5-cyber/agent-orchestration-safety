# Recompute the inherited response aggregates without an API

Use the exact committed scorer version in the report. For any `scoring/<tag>/` folder, read `formal-deliverables.json`, `result.json`, and `prepared.json`; call the existing functions as follows:

```python
from trustfork.scoring.judge_contract import decoded_view
from trustfork.scoring.dynamic_adapter import aggregate_dynamic_scores
view = decoded_view(prepared)
metrics = aggregate_dynamic_scores(
    deliveries, result["result"]["response_judgements"], {},
    assignment_ids={r["response_id"] for r in view["responses"] if r["assignment"] is not None},
)
```

An absent result for a not-applicable pass has no formal deliveries and no paid request. Do not add anchors for TH/TUL when their independent calibration is false. Diagnostic subset values remain excluded from the complete primary result. Goal observations use the original GoalSpec/frozen-workspace observer and are separately captured under `programmatic-goal-state.json`. Request/reply journals preserve actual raw score output, reasoning, finish reasons and usage. This recipe makes no model requests.
