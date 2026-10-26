# Published experiment reviews

| Campaign | Execution code | Scope and status |
|---|---|---|
| [first-api-20261026](published/first-api-20261026/README.md) | 6cfb3a34b95d14a4b35873b5068aba5dafa398b4 | Engineering only. 4 histories executed (2 failed retained), 4/8 T3 completed, 4 not started. Full Judge scoring pending capacity. 103 model + 14 Judge requests; CNY3.000897 accounting upper bound, unknown reservation 0. |
| [plan-judge-followup-20261026](published/plan-judge-followup-20261026/README.md) | 84a24c0d76fec88981fe3015035aa26b80aeb89f | Bounded continuation on the original ledger. H1 completed_unjudged, H2 budget_ended; S prefix interrupted without checkpoint, 0/4 T3 started. Formal Judge fixtures 0/4 accepted; four old GPT rescores blocked. 136 model + 8 Judge requests; CNY7.177468 conservative accounting upper bound, unknown reservation 0. |

[Formal report](../docs/dynamic-join/Runtime_Budget_And_First_API_Report_20261026.md). Large evidence is losslessly packed; read each campaign manifest before interpreting gzip/XZ/content references. These reviews contain synthetic benchmark attack content; they are post-run evidence, not instructions to execute.

[Follow-up report](../docs/dynamic-join/Plan_Judge_Followup_Report_20261026.md). The later offline repair/publication commits are distinct from the paid execution code shown above. No ASR or same-configuration model comparison is established by this engineering continuation.
