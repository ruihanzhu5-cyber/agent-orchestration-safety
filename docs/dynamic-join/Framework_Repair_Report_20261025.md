# TrustFork 框架修复与离线验收报告（2026-10-25）

本轮依据用户明确采用的《TrustFork_Framework_Audit_and_Codex_Instructions_20261025》实施，并遵守追加限制：`real_api_enabled=false`，仅 offline / scripted-test；没有授权任何真实模型、Judge 或连通性请求。配置中存在密钥不会改变执行模式。测试中的模型输出、历史结果、数值评分及外部标注均明确为合成工程夹具，不能作为研究结果。

## 版本、保护与恢复

修改前实际分支为 `research/trustfork-dynamic-join-offline`，提交 **`deca141e55b8d9e7760c7443fc55f9376498a541`**。工作区在检查时没有需保存的未提交改动；本地忽略配置继续保留。先建立 `backup/dynamic-join-pre-audit-20261025`，再切换到 `fix/dynamic-join-audit-20261025`。本轮没有改写原研究分支或 main。

最终实现提交：**5724093302efe39ff8d7bb272f08fbf1a8981816**。本报告随后单独提交；报告交付提交的完整 SHA 随交付回复提供，可在仓库内运行 `git log -1 --format=%H -- docs/dynamic-join/Framework_Repair_Report_20261025.md` 核对。

| 批次 | 独立提交 | 验证 |
| --- | --- | --- |
| 启动、招募、生命周期及消息 | `ed91be4625e23a60d57f515c08a7f81c68984fe2` | 68 通过，0 跳过 |
| 真实操作回执、可见性、标注和目标入口 | `649c0640579a3c29bd924fc4c78b512744c12b09` | 100 通过；最后复核 89 通过，均无跳过 |
| 完整 Judge 请求、可逆表示与评分版本保留 | `a9a4e12a4d7a9c82a1deec7af0c14da8b71994c6` | 106 通过，0 跳过；11 份输入精确往返 |
| 档案、机会诊断与卡等权统计 | `1c7a279c9034fbc4e3d64086aa82566cc3ac05aa` | 主体 119 通过；历史复用复核 113 通过，均无跳过 |
| 最终请求审计和诊断补充 | 5724093302efe39ff8d7bb272f08fbf1a8981816 | 全量 163 通过；随后计数修正后 128 通过；Node 契约 4 通过，均无跳过；8 个 CLI 冻结运行有效 |

恢复上一版时先确认工作区干净；有新改动则先检查并另行保存，不能直接覆盖。以下命令切换到已保存版本，不重写历史、不清理测试证据、不接触 WSL 或 Docker 数据：

```bash
git status --short
git switch backup/dynamic-join-pre-audit-20261025
git rev-parse HEAD
# 应为 deca141e55b8d9e7760c7443fc55f9376498a541
```

如果需要在上一版继续工作，建立独立恢复分支：

```bash
git switch -c restore/dynamic-join-pre-audit-20261025 backup/dynamic-join-pre-audit-20261025
```

另一台已有仓库的机器可先 `git fetch origin`，再从 `origin/backup/dynamic-join-pre-audit-20261025` 建立恢复分支。修复分支与备份分支正常推送；没有强推、合并 main 或自动关闭 issue #1。

## 范围与冻结项

实际代码仓库继续位于 WSL 的 Linux ext4 文件系统；没有移动仓库、安装/升级软件、迁移或清理 Docker 数据。复用已有 Python、Node、Pi 0.84.1、14 项版本/哈希锁定补丁、fd 及已审计 Docker 镜像。任务工具仍全部在 Docker 中执行，保持七工具原有搜索、读取、写入、编辑、截断和错误语义，无宿主回退。

原始提交 `49490514f5187ba4e04b31929f2f4470e0db7def` 的所有已跟踪路径不在本轮修改范围内。30 张原卡、源资产、`cases.json`、source lock、已审查 errata、`profile_templates.v1.json` 及研究矩阵保持冻结。计划仍为 **1664 分支、440 区组（392×4 + 48×2）、144 个预选机制样本、5 张表**；历史/发现/确认卡仍为 4/18/8。

H1/H2/T3、S/F/L、HP/HA/MP/MA、q/r 及布局绑定、H=18/20、M=14/20、R1–R4、补充面板及重复设置不变。行为单请求输出上限 4096、团队累计 48000、120 次请求、每阶段 1200 秒和原并发设置不变。没有新增风险提示、逐操作审批、安全过滤、全队工具串行锁或强制通信。

最终验收发现原物化命令会把 `case_readiness.json` 的已有运行验证证据覆盖成初始状态。已先保存本次自动生成版本，再恢复这一已核实的自生成改动；修复后的物化命令核对源哈希，保留来源匹配的运行证据，只刷新静态映射字段，并拒绝冻结 catalog/errata 漂移。未测试卡不被提升为已通过。最终物化后该文件及冻结数据均与原已提交内容一致。

## I01–I12 处置与证据

| 编号 | 已实现与回归证据 | 实际限制 / 状态 |
| --- | --- | --- |
| I01 | `model_capabilities.py`、`judge_request.py`、绑定/schema、完整准备请求及哈希；独立 Judge 输出预算；容量来源、路由、分词版本和 unknown/declared/verified；无损表示及完整输入审计；未知/超限不发送，行为记录保留；旧评分和新评分版本同时保存。容量、输出、路由、缓存缺失和超长负例通过。 | 有效第三方路由容量、供应商封装开销、正式 Judge 输出预算与限速/费用约束仍 UNKNOWN；实际发送器关闭；issue #1 保持开放。 |
| I02 | S/L 的有限启动段不能被 Main 提前 release/update/cancel 绕过；首次 invocation 完成、4 次请求、预算、硬超时或基础设施终止都有结束记录；启动结束后的未完成工作可继续。真实 S/L 与超过 4 次的后续请求测试覆盖。 | 四次限制只约束初始有限段，不是成员全生命周期请求上限。 |
| I03 | F 的 recruit 只接纳、注册 session；不自动创建 startup/work。真实 recruit-only、后续委派、消息唤醒和不招募测试区分 J/U/U_voluntary。本人摘要随首次实际输入进入，不增加模型调用。 | F 合法结束且不招募/不使用 q 保留在全部有效行为分母。 |
| I04 | 公共 OperationReceipt v2、真实 exec/stream 原结果证据引用；非零退出、超时、取消、异常、缺终帧及 legacy exit 解析；grep/rg 无匹配的正常返回保留。observer 的失败路径也记录，原工具返回不改写。 | 返回成功不等于副作用或目标达成；失败也不能排除部分副作用；并发重叠保留 ambiguous，不靠串行化消除。 |
| I05 | 版本化 claim/action/adoption/goal 标注被实际消费；校验原文 hash/span、actor/epoch、作用域、引用和先接触后动作，acted 需要实际效果证据；冲突显式呈现；actor_reports 不再永久空数组。真实 Pi/Docker 的 C→A 建议、实际写入及标注改变报告的集成测试通过。 | 6 张卡有原确定性 predicate；其余 24 张仅实现证据标注入口，不能宣称自动完成目标评测。离散采样无损害证据不等于 never；不可逆泄露不因文件清理恢复。 |
| I06 | `eligible_complete_blocks` / `card_equal_estimates` 为表 1/2/4 共享 metric-specific 完整四条件集合；卡内布局平均，再卡等权；另保留 all_available_descriptive。30/30 与 0 的卡等权值 15、旧行均值 20 的已知答案回归；缺单条件、metric-specific 缺失及 F 分母测试通过。 | bootstrap 10000、seed=20261024、family8、缺失敏感性、补充/重复分离及共享前缀费用去重保持；原任务族映射仍待来源依据，不新增独立性假设。 |
| I07 | delegation 版本及 prepare/update/cancel/start/release/complete/阶段事件均带作用域；许可时重新核实队列工作来源，保留真实 peer/continuation；checkpoint 保存 continuation；已开始整批工具不被截断丢弃。 | 不新增全局调度串行化。 |
| I08 | 每条消息×收件人的投递/曝光/阶段终态可重放，保留正式 deliverable 和源事件链接；每次真实重复曝光独立记录；保留原 message 级覆盖率并新增 recipient 级覆盖诊断。 | 不自动将 peer 消息抄送 Main，不强制 q 发消息，不把非 Main 收件的终止输出当 Main 输入。 |
| I09 | A/B 建立 none 外部档案，0 条外部记录和空统计；直接合作次数来自真实/明确 synthetic 的 HistoryBundle task occurrence，区别于成功次数。C/D 的模型名取布局对应精确配置，未知为 null。真实前缀复用测试验证先恢复历史再构建档案、共享实际前缀和一次计费。 | 离线精确实际模型绑定未解析，不用 actor 字母推断；20 条合成档案不是当前模型的 20 次真实任务成绩。 |
| I10 | 冻结 v1 材料；记录 schema/corpus/renderer、展示顺序和实际模型绑定；实际输入索引区分初始 records、本人摘要和查询结果进入后续输入。相同查询结果的多来源保留歧义。 | 没有查询不等于没有看过初始档案；材料认知/信誉效应没有在本轮测量，不升级材料来追求 ASR。 |
| I11 | `visibility_index.py`、`risk_opportunity.py` 及 CLI；区分 submitted_input / successful_response、Main 可见 / 评测全环境、任务包 / 交接 / peer / tool / 原资源 / 档案。原资源 snapshot 和实际 system span 单独追溯；私有目标绑定仅控制侧检查，不输出目标正文到机会报告；原八指标 Main 主体保持。 | 精确匹配未覆盖所有部分/截断读取；原 IPI 语义仍需有据标注。30 卡逐卡记录 source refs 和当前 user_request→public_task_brief 共享策略；原文接收者/用途的语义解释仍 UNKNOWN，不能自行新增秘密或 ACL。 |
| I12 | 关闭真实 provider / Judge；只允许 offline / scripted-test，formal readiness 明确 false；按真实请求/响应提供方和 guard 日志核对，不用配置中存在密钥或摘要固定 0 推断调用数。 | 真实 provider adapter、真实 H1/H2 执行、正式 Judge、精确绑定和真实发现样本复核仍未实施/未验收；不是 formal ready。 |

所有机会结论均为被动诊断，不生成“足够危险”总分，不将接触、采纳、动作、效果或 Main 编排失败合并成一个布尔量。peer 的标注保留 consumer_actor，不能把 A 的动作说成 Main 看过或采取了建议；原 RTF/RSR/IAS/SAF/VF/EI/TH/TUL 的 rubric、纯聚合函数和 0–100 方向保持。没有正式交付的 actor 的回答分数为 N/A。

## 完整 Judge 输入与可逆表示实测

对原 issue 所用十份已保存评分输入逐份复测，并增加显式合成的六阶段长输入；不是重建或伪造旧结果。先保留原 sanitized legacy view，再对完全相同子结构/长字符串建池。每个请求内包含完整内容池，保留事件顺序、actor/stage、请求快照及每次重复出现；保留 Unicode、null、数组及字节的 base64 表达。缺引用、循环、篡改、保留标记转义与精确 canonical/hash 往返均有测试。没有摘要、删旧 stage、删除工具结果、外部引用、gzip 代替 token 测量或分块打分平均。

| 输入 | 原 view tokens | 完整 legacy 内容/schema 估算 | 完整可逆内容/schema 估算 | 参考128K、预留4096、未计未知framing（legacy / 可逆） |
| --- | ---: | ---: | ---: | --- |
| p001/HA | 95,891 | 96,538 | 45,763 | 参考内 / 参考内 |
| p001/HP | 95,750 | 96,397 | 45,614 | 参考内 / 参考内 |
| p001/MA | 94,950 | 95,597 | 44,751 | 参考内 / 参考内 |
| p001/MP | 95,889 | 96,536 | 45,701 | 参考内 / 参考内 |
| p006-primary/HP | 97,523 | 98,170 | 48,475 | 参考内 / 参考内 |
| p006-r70/HP | 128,619 | 129,266 | 57,866 | 超参考 / 参考内 |
| p024/HA | 184,926 | 185,573 | 90,431 | 超参考 / 参考内 |
| p024/HP | 185,230 | 185,877 | 90,741 | 超参考 / 参考内 |
| p024/MA | 186,684 | 187,331 | 91,879 | 超参考 / 参考内 |
| p024/MP | 186,062 | 186,709 | 91,247 | 超参考 / 参考内 |
| 合成六阶段长夹具 | 5,809,036 | 5,809,683 | 19,366 | 超参考 / 参考内 |

上述 token 数是本地已有 `tiktoken 0.14.0 / o200k_base` 对解码后的消息内容和本地 schema 表示的估算，不是 HTTP wire 大小或供应商 usage；role/provider 转换及 framing 未知。完整请求包含原 rubric、固定格式说明、完整用户内容、工具和参数；额外输出预留 4096 **仅用于诊断对比**，正式 Judge 预算仍为 null。128000 也是参考情景，不是对别名或第三方路由真实能力的断言。供应商 framing 未知，实际路线一律 capacity_unknown，`can_send=false`、`formal_ready=false`。

诊断另列 system/history、事件、工具结果/schema、档案、workspace、rubric 和格式说明；这些是重叠结构视图，不能将占比简单相加。容量报告保留 source/evidence/verified_at、路由、tokenizer、request_hash、representation、预算与原因。无损往返证明信息保留，**不能证明 Judge 的认知或评分等价**；后续需在两种表示均能装下的真实发现样本比较，目前没有执行。

独立 rubric 文本为 637 tokens、格式要求 10、可逆格式说明 119。HTTP JSON 的转义会在请求解析时还原，wire 序列化 token 数必须单列，不能当作模型内容预算。候选输入按解码后的系统/用户消息内容和工具/response schema 估算；参数进入请求哈希，但不自动视为模型文本；供应商额外 framing 仍未确认。早先基于 wire 序列化得出的“十份均超128K”已撤回，最终结论只使用修正后的口径。

评分版本以 scorer/run/annotation/mode 哈希确定，旧平面输出先归档，版本目录不可被不同内容覆盖。影响评分的 codec/request/capability/annotation/schema/metric_specs 及实际配置进入哈希。评分故障不重跑团队；可对冻结轨迹生成新评分版本。

## 离线验收与调用审计

最终保存的验证结果：

- `acceptance-v2/full-tests.xml`：**163 通过，0 失败/错误/跳过，926.668 秒**；覆盖全部单元与真实 Pi/Docker 集成。
- 随后修正 wire 与模型内容计数混淆后，`batch5-final-count-correction.xml`：**128 通过，0 失败/错误/跳过，124.964 秒**，包括全部 126 项单元测试、真实标注证据链与真实补充前缀复用。全量 163 的那次运行在该纯计数修正前；不把它冒称为修正后的重新全量运行。
- Node `typecheck` 退出 0；`test:contract` **4 通过、0 跳过**，包括远程工具语义、原按文件队列的别名/并发行为与本地拦截负例。
- 离线 preflight、30 卡物化、冻结计划生成均退出 0；计划实测 1664/440/144，静态物化后原 readiness 和冻结文件没有 Git 差异。
- p001/S 与 p024/F 各四条件 CLI，**8/8 为 valid_behavior**；一次只执行一个任务容器组。p024 保留原三个阶段及原 new_session 切换。
- 五张 JSON 表及五张 CSV 表已生成，均为 test-fixtures 水印；缺失计划分支保留为未运行，没有执行 1664 个真实试验。
- 最后只对这八份冻结记录重评分：八份原 run 文件哈希未变，八份旧评分版本保留，八份新评分版本均有独立 ID；原因记录于 `final-corrected/rescore-reason.json`，没有因计数错误重跑团队。
- 原十份输入加长夹具 **11/11 精确往返**；新八份输入加长夹具 **9/9 精确往返**。最终容量数使用 `judge-input-audit-corrected.json` 和 `final-corrected/judge-inputs-new.json`；旧 wire 口径文件保留作追溯，不用于上下文判定。
- 原始提交 49490514 的已跟踪路径改动数 **0**；`git diff --check` 通过。

初次全量执行保留了 152 通过、1 失败的记录：旧“4 次启动请求后继续工作”测试只手工排队，没有建立真实工作来源，新的许可检查正确拒绝它。修复仅让测试建立并释放实际 runtime_startup 委派，六轮真实工具请求沿该 invocation 继续，验证初始计数停在 4、后续工作继续且不把终止输出偷偷发给 Main；没有放宽运行器许可检查。修复后的针对性回归为 125 通过；物化保护另有 2 项通过，之后再执行最终完整验收。

实际命令和退出码保存在本地忽略目录 `build/dynamic/framework-audit-20261025/`。其中完整验收根为 `acceptance-v1/`；重评分与最终复核另存新目录，保留最初失败和修复后的结果。主要复现命令如下，输出目录须选择新路径：

```bash
python -m trustfork.tools.preflight_dynamic --mode offline --out <out>/preflight.json
python -m trustfork.tools.materialize_dynamic --all-cases --out <out>/cases
python -m trustfork.tools.generate_dynamic_manifest --plan-only --out <out>/plan.jsonl
python -m pytest tests/dynamic/unit tests/dynamic/integration -q
npm --prefix trustfork/runtime/dynamic run typecheck
npm --prefix trustfork/runtime/dynamic run test:contract
python -m trustfork.tools.run_dynamic --mode scripted-test --case p001 --protocol S --conditions HP HA MP MA --trial-workers 1 --out <out>/scripted/p001
python -m trustfork.tools.run_dynamic --mode scripted-test --case p024 --protocol F --conditions HP HA MP MA --trial-workers 1 --out <out>/scripted/p024
python -m trustfork.scoring.aggregate_dynamic --mode test-fixtures --input <out>/scripted --out <out>/tables --plan <out>/plan.jsonl
python -m trustfork.tools.audit_judge_input --input <saved-inputs> --out <out>/judge-audit.json --include-long-fixture
python -m trustfork.tools.audit_risk_opportunities --input <out>/scripted --out <out>/opportunities
python -m trustfork.tools.audit_model_calls --root <saved-runs> --guard-archive <saved-guard-jsonl> --coverage-gap '<known gap>' --out <out>/calls.json
git diff --check
```

p028 的原 MEMORY.md 场景与 p024 的真实多阶段/new_session 切换分开覆盖，未修改原卡或研究矩阵。L 的原进度 checkpoint、原资源读取、真实工具错误/截断/文件队列、宿主 trap、stage drain/cancel、新旧会话及补充基线复用由集成测试覆盖。所有容器组顺序执行，没有用重复启动代替排查或测试失败处理。

最终调用审计文件为 `calls-final.json`，未使用任何摘要的固定零值：

| 证据范围/计数 | 实测 |
| --- | ---: |
| 留存实际运行记录文件（工程回归，非独立研究样本） | 75 |
| 去重 T3 模型提交，响应 provider 为 scripted | 854 |
| 该范围真实模型请求 / Judge 请求 | **0 / 0** |
| 来源未解析的模型 / Judge 提交 | 0 / 0 |
| 原始 guard 收据 / 去重 RPC / 重复副本 | 2052 / 2004 / 48 |
| scripted execute_turn 收据（含独立/历史/重试控制调用，不等于 T3 模型数） | 1082 |
| 正常运行外发尝试收据 / 宿主 I/O 违规收据 | 0 / 0 |
| 请求事件冲突 / 读取错误 / 不完整 guard 收据 | 0 / 0 / 0 |
| 因已知日志缺口，完整历史累计模型 / Judge 调用 | **UNKNOWN / UNKNOWN** |

另对旧 V9 十份封存运行单独审计：141 次去重 scripted T3 提交、真实模型 0、Judge 0；452 个唯一 guard RPC、248 个 scripted execute_turn 收据，后者还包含独立/历史调用，不能当作 T3 样本数。它们已纳入组合去重，不重复相加。本轮没有在留存日志中发现此前的真实模型/Judge 调用；对缺失历史不作零次保证。本地配置最终核实仍为 offline、real_api_enabled=false；密钥文件保留在本地忽略配置中，权限0600。

调用数不使用 run.json 中既有固定 0，也不使用 guard 初始化的 real_model_requests / real_judge_requests 作为证明；以提交事件、实际响应 provider、独立 guard network 计数及收据去重核对，包括失败尝试。请求来源不明、冲突或日志缺失时输出 UNKNOWN，不当作安全 0。Node 负例的 fetch 在本地 guard 抛错后结束，不会发送连通性请求。

早期测试采用 pytest 默认保留策略，部分本轮原始临时日志在改用持久 basetemp 前已被轮换删除；保留下来的根目录日志已复制归档，之后每次测试使用唯一持久目录。这个覆盖缺口必须保留：**可审计范围内观测数与整个历史累计数分开报告，不能用后续重新运行的日志补造此前记录。** 旧 V9 的 452 条归档 guard 收据也单独纳入去重检查。密钥值没有写入代码、报告或 Git；本地配置继续忽略并保留。

## 未解决项与后续边界

`formal_ready=false`。还缺实际路由容量及适用 tokenizer/framing 的依据、独立 Judge 输出/RPM/TPM/费用预算、真实 provider 工具/错误/重试适配、真实 H1/H2、正式 Judge，以及可逆表示的真实发现样本一致性复核。本轮没有借别名推断这些设置，也没有启用 API 去探测。

24 张语义目标卡、原接收者/用途解释、部分/截断资源读取的来源归因和第二标注者复核仍需要有据的后续标注；已实现入口及校验不等于已有完整标注数据。完整 workspace 不能证明其他路径或外部服务全状态，离散观测不能证明没有瞬时损害。当前合成材料和工程回归只能证明流程/合同/证据连接在所覆盖场景下工作，不能证明真实攻击成功率、信誉效应、模型性能或论文结论。
