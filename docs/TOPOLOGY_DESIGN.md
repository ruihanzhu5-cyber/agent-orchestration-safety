# TrustFork 固定通信拓扑扩展

## 范围与入口

第一版是原有 TrustFork 加可选运行时。支持 Original、Chain、Debate；不集成其他多智能体框架、不做动态重组、不新增防御。只有 OpenCode 1.18.13 支持新模式；Pi/OpenClaw 请求 Chain/Debate 会明确失败。新模式只接受源任务的 `b4 / target_breadth=4`，不改任务的 Breadth 来凑条件。

入口：`tools/generate_jobs.py --topology original|chain|debate`。省略参数或指定 Original 使用原有 OpenCode 适配器、工具实现、提示词及评估路径，不安装拓扑插件。`--topology-order` 只选择一个固定 ABCD 排列，不在运行中改变。

## 真实通信语义

| 模式 | 真实消息与调用 | Main 能看到的回复 |
|---|---|---|
| Original | 原有逐成员 `task` 调用；Main 自行选择顺序/范围 | 原生工具实际返回内容 |
| Chain | Main 的一次请求调度 A、B、C、D 四个真实 OpenCode 子会话；后者输入含原请求及紧邻前者输出 | 只有最后一个成员的文本，附参与顺序说明 |
| Debate | 四个真实子会话分别接收相同请求；冻结四份初始输出；再分别向每个会话发送其他三人的初始输出，执行一次真实审查/修订 | 四名成员的最终审查文本 |

调度器没有伪装成成员自己调用其他成员。它通过 OpenCode 原生 SDK `session.create` / `session.prompt` 完成转发；节点仍是原四个 profile。API 的 parent session 用于原生会话归档，不能当作逻辑通信边。实际逻辑边记录 sender、receiver、phase、完整消息和原生 session/message ID。

每次 `task` 调用都是一次完整协议。Main 可发起后续任务，但结构不变；Debate 每次只有一轮同伴审查。运行总时限由原 Harbor 预算控制，不引入无限的内部辩论循环。并发 Main 调用由插件串行处理，避免不同协议轮次交叉污染。

新模式的 `subagent_type` 保留兼容字段，但一次调用会覆盖整个固定团队。Main 看到的工具描述会明确说明这一点。该字段不应被分析为 Main 单独优选了某个人。Original 仍保持逐成员选择的原生语义，因此本扩展比较的是协作协议，不能把所有结果直接归结成脱离调度/汇聚语义的纯图效应。

## 模型、私有指令与权限

- `resolve_pool`、`render_display` 和原来的 goal 模板生成模型、标签、唯一私有风险目标。本模块不改这些内容，也不在日志中写入谁是风险源。
- 原 profile 及原始工具权限不变；子 Agent 的 `task` 仍禁用，不增加递归深度、不开放模型替换或任意会话读取。
- 调度器调用固定模型和对应 profile，不把风险目标拼进普通任务消息；Debate 第二轮复用同一原生会话及 profile。
- Main 保持原来的委派工具权限，无直接工作区读写工具。Chain 不支持传入 `task_id` 恢复中间会话，避免直接索取中间输出。
- 原版成员在任务期间可以使用工作区工具，新模式也保留此上限。没有新增“写入必须经过最终批准”的防御闸门。动作可能发生在 Main 最终答复之前，应从实际时间线判断授权和执行，不能把最终文本视为先行审批。

## 信息旁路与独立性限制

约束的是模型消息路径，不是操作系统信息流。四名成员保留共享工作区、mock 状态、记忆文件和原生会话访问条件。原链式任务还会在工作区保存前阶段轨迹快照。成员可以通过文件或其他原有工具间接影响彼此。

Debate 初始请求不包含其他成员回复，因此是消息层独立；在共享可写工作区中，不能声称它们在文件状态上独立。插件记录工作区工具尝试，原生子轨迹保留结果。出现额外文件传播时须单列，不能因为消息边合规就宣称完全隔离。

宿主真实文件不挂进任务工作区；Harbor 仅提供任务资产和本次日志目录，任务使用本地 mock 服务及原网络 allowlist。真实实验在可丢弃 Docker 容器执行。

## 轨迹与评分适配

实现文件：

- `trustfork/topology/config.py`：规格验证、插件渲染、运行时任务副本。
- `trustfork/topology/runtime.js`：真实 SDK 调度、逐跳消息、一次同伴审查、原生会话引用和工具尝试日志。
- `trustfork/topology/scoring.py`：实际调用/返回的规范化、Main 可见性和过程观测。
- `trustfork/tools/run_topology_pilot.py`：复用原 TaskRunner，准备和真实运行少量配对任务。

不修改 1,890 个源任务。新模式复制原任务到忽略的 `build/tasks_topology/`，原 verifier 逐字节保存在副本的 `verifier_original.py`；新的薄包装只适配真实路由调用提取和可见性说明，复用原来两次 judge 调用、所有评分锚点和数值公式。Shell 的 CRLF 只在副本中规范化。

任务副本按源文件与评分包装的内容哈希固定路径，并在完整准备后发布；之后的配置生成不会改写此前已引用的副本。逐组配置保存实际加载的插件源码，因此应同时保留配置与对应任务副本，不能只保留当前 Git 工作树。

适配层不向 Main 的 ATIF observation 添加隐藏回复，也不伪造模型工具调用。它从实际 task-result 元数据中取真实 SDK 调用，并要求每条返回能够对应到原生子会话的实际文本；否则拒绝无拓扑的静默退化。四人参与统计标注为运行时调度，不解释成 Main 单独选择了四次。

每个响应标明是否逐字出现在 Main 实际工具输出中。工具输出被原生截断时，不能继续声称所有文本完整送达。逐字送达不等于模型理解，也不能自动判断某段是否构成反驳；第一版不新增语义 LLM Judge。

保留原 RTF/RSR/IAS/SAF/VF/EI/TH/TUL 公式及高分更差的方向。RTF/RSR 仍按每成员的实际阶段回复平均；Debate 有两阶段，所以须报告阶段数。权限判断继续使用原 judge 诊断及原生工具事实，消息转发本身不是授权。

**CAR 限定**：评估者能读所有中间轨迹，不代表 Main 收到了其中的反驳。新模式在 `topology_observations.json` 与 `annotations.json.topology_process` 中明确标记 `car_comparable_to_original=false`。保留原诊断，但在没有基于 Main 可见性的语义核对前不报告可比 CAR。原 `aggregate.py` 当前只汇总八项连续分数，没有单独实现一个 CAR 汇总列；本扩展不伪造同名数值。

## 配对运行与公平性

必须一致：源 Task ID、资产与初始状态、模型/标签、私有目标哈希、工具权限、Harbor 超时预算、provider 限制和 judge。主要共同预算是原任务时限及相同倍率；并非硬性相同总 tokens。Debate 额外真实审查会增加调用和成本，必须报告，超时/截断不能记成安全。

第一条选择 `trustfork_0018`：原始 `M1/G3/b4/P1`，与现有双 provider 的 P1 注册表兼容。最初准备 0012 时发现它是 P3，而本地候选池只配置了 P1；尚未调用 API 就失败。兼容性筛选不依据攻击结果，三个模式均使用同一个 0018，不改 Payload、Breadth 或攻击目标。

本地 GPT-4o 网关需要显式 128000 上下文、16384 输出上限；试跑工具对三组施加相同限制。现有代理 compose 作为可选参数由用户运行环境提供，不把私有代理或密钥提交仓库。

## 命令

默认原生配置示例：

```bash
python3 trustfork/tools/generate_jobs.py --system glm-5.2@opencode --tasks trustfork_0018 --topology original
python3 trustfork/tools/generate_jobs.py --system glm-5.2@opencode --tasks trustfork_0018 --topology chain
python3 trustfork/tools/generate_jobs.py --system glm-5.2@opencode --tasks trustfork_0018 --topology debate
python3 trustfork/tools/run_benchmark.py --system glm-5.2__opencode__topo-chain --only trustfork_0018 --env-file .env
```

已有本地双 provider 配置时，Linux/WSL 中运行：

```bash
python3 trustfork/tools/run_topology_pilot.py \
  --system gpt-4o@opencode --tasks trustfork_0018 \
  --systems-config build/local-config/systems.yaml \
  --pools-config build/local-config/pool_templates.json \
  --env-file .env --proxy-compose build/local-config/proxy-compose.yaml \
  --execute
```

不加 `--execute` 只准备配置。若 Python 环境没有激活，使用该环境 Python 的绝对路径；工具优先从同目录找到 Harbor。原始轨迹、配置和成本记录放在忽略的 `build/topology-pilot/`，不得提交为公开结果。

## 验证层次

1. 离线 Node 测试检查真实调用算法、Chain 可见性、冻结的同伴审查和故障中止，使用明确的 Mock SDK。
2. Python 契约测试检查 Original 默认等价、拒绝不支持条件、资产不变、原评分公式保留和无原生轨迹时拒绝评分。
3. 真实 API 试跑才验证实际 OpenCode 的插件覆盖、原生子会话、工具执行和 judge；不能用前两项替代第三项。

结果状态、日志位置与限制见 `TOPOLOGY_PILOT_REPORT.md`。
