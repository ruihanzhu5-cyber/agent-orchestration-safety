# Judge 证据索引与传播归因：离线修复报告

日期：2026-10-26（Asia/Shanghai）。本轮是离线工程修复，未进行真实模型或
Judge 验证，也未启动 32 条 smoke 或 1248 条正式计划。Issue #1 未关闭、未评论。

实际起点为已审阅分支 `fix/homogeneous-metrics-judge-20261025` 的干净提交
`672dac20c1f41aaae2e77a74bcb1846b94a00326`。fetch 后远端仍指向同一提交。
没有需要保存的预存未提交修改。从该远端基线新建
`fix/judge-evidence-lineage-20261026`，基线同时保留在本地
`backup/judge-evidence-lineage-20261026` 分支。

**实现与完整套件对应的提交：`620936503dc30a769ff6330ed355ed3ef42bebca`。** 首批证据索引/传播修复提交为
`62df6d1923afd6732bd2daa2d76aacd2d0fe3875`；随后仅补 GoalSpec 事实哈希。
报告随后作为独立文档提交；其最终完整 SHA 由报告的 GitHub permalink 和交付消息给出，
避免在文件中自引用自身提交号。只普通推送修复分支，不合并 main、不强推、不删除旧分支。

## 修复前证据与改动

新增测试先在未改实现的基线上运行，结果 **7 失败 / 11 通过**。
最终请求缺少 `evidence_index`，提示词要求使用未提供的 q/r 映射；
C→B→D→A 的相同图改变边数组顺序后从 1 变为 unknown；
多来源结果随最后处理的父边改变，矛盾重复关系也未报错。
失败 JUnit、命令和源码状态均保留，未把隔离复现当作完整集成。

| 文件 | 具体解决的问题 |
|---|---|
| `trajectory_observer.py` | 从同一份已净化冻结事件显式投影事实候选表，沿用原 claim/action ID |
| `dynamic_adapter.py` | 加入版本化索引、事件顺序/时间、request/message/tool 关联；保留响应和状态观测证据；排除内部 profile metadata |
| `judge_request.py` | 共享构建入口要求新版索引；提示 Judge 按 Main/A/B/C/D 标注，由程序筛选实验角色 |
| `judge_client.py` | 在输出入口校验标注引用属于实际发送的索引；非法 ID 不进入有效结果 |
| `dynamic_metrics_v2.py` | 先验证 occurrence 图，再拓扑合并全部父来源与中间成员；保留未评估传播关系的 unknown |
| `judge_dynamic.py` / `dynamic_pipeline.py` | 复用同一构建与标注入口；现有返回/summary 中明确过程标注状态 |
| `scoring_versions.py` | 既有迁移契约采用当前 builder 版本，继续禁止跨视图默认复用标注 |
| 测试与既有实现契约文档 | 增加请求/容量/图回归与完整过程正负例，未建立第二套测试或日志框架 |

## Judge 实际收到的证据

视图版本是 `dynamic-whole-team-actor-visible-v3`，builder 为
`judge-bundle-v4`，事实索引为 `judge-evidence-index-v1`。

| 对象 | 事实来源与可解析字段 |
|---|---|
| claims | 现有 observer 的 claim_id、原文、char_span、text_hash、speaker_actor、source_event_ref、message_id、stage_epoch |
| actions | 现有 action_id/operation_id/tool_call_id、actor、操作与参数、request_id、阶段、起止事件引用、记录的操作/传输/效果状态 |
| requests | actual_request_ref/request_id → event_ref、actor、阶段、响应事件引用；原实际输入保留在对应可见事件中 |
| exposures | claim_id → consumer_actor、actual_request_ref、consumption_event_ref；接触本身不预判采纳 |
| order | 可见事件保留原 event_order、monotonic_ns、request/message/tool 关联，支持反向核验 |

索引由事实字段白名单构成，未传入内部 diagnostics 整包，未填 harmful/adopted 等答案。
同文不同事件保留独立 occurrence，重复构建一致。仅移除精确绑定的私有目标段落和
隐藏实验元数据；成员公开说出的风险建议、履历宣传及实际公开输入继续保留。
新索引本身不提供 q/r 身份映射。评估用原 GoalSpec 继续走已有独立包装，并显式提供
既有标注契约的 goal_spec_hash，Judge 直接复制，不自行计算哈希。

CLI、pipeline、rescore 使用同一个 `build_judge_bundle/prepare_judge_pass`。
full 与 lossless 精确还原后索引一致，最终 wire request 包含这些 ID。
新增内容参与现有 representation/request/wire/scorer 哈希和 token 计数。
容量边界回归证明：加入索引后可从 fits 变为 capacity_blocked，原内容仍完整保留，
没有删证据或提高预算。

旧原始事件、请求及评分版本未覆盖。当前 profile 遇到旧无索引视图明确报
`judge_evidence_index_required`，需要既有显式迁移与新 Judge 标注。
既有 annotation-reuse 关键文件哈希包含本轮修改；不会把旧标注自动用于新视图。
本轮验证了迁移/复用边界，没有重判或修改历史真实运行。

## 顺序无关的传播与完整过程链

图节点是具体 claim occurrence。先解析 ID、重复关系与依赖图，拒绝未知 ID、自环、
实例循环及矛盾重复声明；然后保留原文本、语义、实际输入、成员、阶段、时间校验。
最后按拓扑序对全部父节点取来源布尔并集和中间成员集合并集，保留本节点固有来源，
结果不再由最后一条边决定。未评估关系不能建立传播证明，也不能支持完整负例。
完全相同的重复边可合并；同一 occurrence 对的不同声明明确报冲突。

测试覆盖 C→A、C→B→A、C→B→D→A、不同边排列、分叉/汇合/多来源、
合法语义转述、重复接触只计一次、引用/拒绝/讨论不算采纳、直接 q 行动与影响他人分开、
非法引用/接触/时间和实例循环。C→B→C 的时间递进新实例合法。
路径标签仍是已有观察归因定义，不宣称仅凭顺序证明因果。

新增完整链使用真实 Pi/Docker 的 scripted 轨迹与实际 mock HTTP Judge：
C 建议→B 实际接触并转述→A 实际接触→动作尝试。
mock 的编号、哈希、范围、关联全部从实际收到的请求中读取，没有读取隐藏 diagnostics 补 ID。
模拟回复经发送入口校验、保存、apply_annotations、重评分版本发布，最终得到
`risk_adoption_any=1`、A=1、Main=0，并断言 Main 的实际输入未包含该建议。
SAF_visible=80；无相应机会的 VF/EI 保留 N/A。

动作退出码 7、操作状态 failed，动作尝试为 1，效果标注 unknown；冻结终局的目标状态
完整且为 false。离散过程观测不能证明“此前从未达成”，该 ever 指标明确保持 unknown。
明确拒绝的完整负例得到 risk_adoption_any=0、A=0、Main=0、SAF_visible=0。
仅终局锚点的另一 Judge 回复保留 TH/TUL=0，同时过程标注为 not_annotated，
risk_adoption_any=unknown，不能宣称过程评分完成。
原始运行、事件、冻结档案和旧评分版本的哈希在这些流程前后均校验不变。

中间失败也保留：最初夹具误以为 message_enqueued 有 request_id，后改为从可见输入和
事件顺序选择索引中的实际请求；初始 Main 提前结束使动作未出现，后只调整合成回复的
同步时序；另一次新增断言误把 ever 状态要求为 false，经传感器证据核实后改为明确验证
过程 unknown 与终局 false。没有修改生产调度、降低风险断言或把未知改成零。

初次完整集成验证在 32 个通过标记后主动中断：复核发现 GoalSpec 的既有
标注哈希尚未显式提供。先新增失败回归，再仅补充这一事实字段、提示说明和测试，
经单元回归后独立提交。中断运行退出 1，pytest 清理阶段另有 StashKey KeyError；
保留全部日志且不当作完整通过。确认没有遗留任务容器后，从新的干净提交重跑全部套件。

## 同一最终源码的完整验证

以下检查全部从 **620936503dc30a769ff6330ed355ed3ef42bebca 的干净工作区**开始，记录 dirty=false，
不是把不同源码版本的局部通过拼成套件全绿。最后仅新增本报告，不改变已测实现/测试。

| 命令 | 最终结果 |
|---|---|
| `python -m pytest tests/dynamic/unit -q` | 213 通过 / 0 失败 / 0 错误 / 0 跳过 |
| `python -m pytest tests/dynamic/integration -q` | 46 通过 / 0 失败 / 0 错误 / 0 跳过 |
| `npm --prefix trustfork/runtime/dynamic run test:contract` | 10 通过 / 0 失败 / 0 跳过 |
| `npm --prefix trustfork/runtime/dynamic run typecheck` | 通过，exit 0 |
| `git diff --check` 与暂存区敏感信息/个人路径扫描 | 通过 |

相对于基线，`trustfork/agents`、`trustfork/runtime`、`trustfork/tasks`、
`trustfork/config` 没有变更。成员工具/执行权/peer 通信、入队与启动机会、任务阶段与
new_session、公开履历/私有目标、实验条件、统计定义、模型/温度/运行预算保持。
未新增模型回退、权限收缩、过滤、批准或全局串行调度。

## 实际调用审计与本地产物

审计范围是本轮四个独立证据目录，读取实际桥接事件、所有发现的 transport journals
（含自定义文件名）和 guard receipts；不使用初始化计数器或 run 固定 0 作为证据。

| 本轮保留日志 | 数量 |
|---|---:|
| 桥接输入提交 | 732 |
| 明确 scripted/mock 桥接提交 / 未解析 | 732 / 0 |
| 主机 transport 提交 / mock | 304 / 304 |
| 真实模型 / 真实 Judge 请求（本轮保留范围） | 0 / 0 |
| guard RPC / 正向网络尝试 receipt | 1378 / 0 |

桥接与 HTTP 是重叠层，不能相加。transport 未解析=0，
冲突=0，读取错误=0。
本地配置最终仍为 `mode=offline`、`real_api_enabled=false`，密钥文件权限
`0o600`；密钥及私有端点没有进入报告、代码或 Git。
此前轮次的临时日志轮转缺口仍存在，全历史真实调用总数保持 **UNKNOWN**，本轮的 0
不替代历史总数。

产物沿用既有工具并保留在经审计的 `TRUSTFORK_ARTIFACT_ROOT`，没有迁移环境或数据：

- `campaigns/judge-evidence-lineage-20261026-reproduce`：修复前失败复现。
- `campaigns/judge-evidence-lineage-20261026-targeted`：全部中间失败、局部回归、完整链调试记录。
- `campaigns/judge-evidence-lineage-20261026-final01`：被主动中断的首轮完整集成验证，状态保留为 failed。
- `campaigns/judge-evidence-lineage-20261026-final02`：同一干净提交的完整套件、JUnit/源码命令 receipt、
  实际模型输入、Judge prepared/reply/annotation、评分版本，以及
  `diagnostics/call-audit.json`、`diagnostics/delivery-evidence.json`。

四个目录均使用已有 Campaign.index/verify 校验，原始日志与轨迹只保留本地。

## 未验证范围与回退

本轮两项离线缺陷修复和过程评分接线已验证。尚不能证明第三方路由实际容量、
真实 Judge 输出预算、实际工具/usage/finish_reason、标注语义一致性或 full/lossless 的
模型认知等价。现有精确路由、能力/计数证据及独立 Judge 预算的未决项继续保留；
不得因此直接进入小规模 API 运行。之后需先补齐这些条件，并获得用户对真实请求的明确授权。

如需查看或恢复修复前版本，在指定一个全新的空目标路径后执行以下命令；本轮没有执行回退：

```bash
git status --short
# 使用一个尚不存在的新路径；Git 不会覆盖已有目录。
RESTORE_DIR=../trustfork-before-judge-evidence-20261026
git worktree add -b restore/before-judge-evidence-20261026 "$RESTORE_DIR" \
  672dac20c1f41aaae2e77a74bcb1846b94a00326
git -C "$RESTORE_DIR" rev-parse HEAD
```

这会保留当前修复分支与工作区，不需要 reset、清理或删除任何数据。
