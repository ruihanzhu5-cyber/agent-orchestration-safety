# TrustFork v9 开工审查报告

日期：2026-10-24。审查对象：dynamic-join-v9-trajectory-portfolio项目说明及同版代码指令。结论：**READY_FOR_OFFLINE_IMPLEMENTATION**。

用户明确授权更新方案、派agent复审、通过后发布Codex指令。本轮3个独立agent分别负责信誉/实验设计、轨迹评测、工程启动条件；初审发现的问题已直接修入主文并复核，不要求实现者自行决定研究语义。

## 1. 审查结论

| 审查 | 结论 | 关闭的主要问题 |
|---|---|---|
| reputation_design_review | 离线开发可开工 | 主renderer、视图投影、近期按需、冻结素材、结果差异白名单、样本仅一致性、q/r独立配置绑定 |
| trajectory_evaluation_review | 离线开发可开工 | 原TH/EI含义纠正、过程主指标族、动态peer claims、原/扩展评分分离、未知与分母、八项人工复核 |
| engineering_start_review | 离线开发可开工 | 公平队列、stage先收尾、Pi错误空响应、唯一重试、目标维护、并发归因、new_session消息条件 |

“通过”指研究合同足以开始实现和写测试；不是证明实现已存在、攻击有效或全部环境兼容。支持包的静态校验也不是生产运行测试。

## 2. 本轮具体改动

1. 研究主要过程指标锁定IAS/SAF/VF/EI；保留RTF/RSR/TH/TUL。原TH已包含恢复前危害，新增贡献定位动态事件来源、时序与成员归因。
2. 2个Main×4项过程指标共8个确认比较；同步主表、消融列、区间和人工复核。未新增总风险分，未按结果改卡。
3. 履历主输入固定portfolio_neutral_v1：20条中性档案、类别统计、可查样本；近期按需。冻结20模板；不得让Codex自由编写故事。
4. 旧summary示例明确只是基础字段；完整summary必须含类别统计。q/r历史配置按actor+版本区分。样本只能证明与合成档案一致，不冒充20次真实执行。
5. 原response claims与中途消息claims分离；消费、采纳计划、行动、状态、恢复独立记录。观察器离线，不拦截模型行为。
6. FIFO公平调度、STAGE_CLOSING、new_session条件化消息迁移；仍保留4个Sub并发、七工具与peer，未给风险成员优先。
7. Pi error/aborted空assistant不是成功空交付；host唯一重试；跨turn/恢复/维护核对私有目标；并发状态含重叠操作和模糊归因。
8. 逻辑模型仅gpt4o/deepseekflash；judge为gpt4o。精确API ID不猜版本，离线模式不开付费请求。

## 3. 代码依据与起点

- 原作者：[固定基线49490514](https://github.com/henrymao2004/agent-orchestration-safety/tree/49490514f5187ba4e04b31929f2f4470e0db7def)。本轮重新读取agents/pi.py、config/actor_goals.json、scoring/verifier.py。
- [Pi core v0.84.1](https://github.com/earendil-works/pi/tree/v0.84.1/packages/agent/src)：本轮主审读取agent-loop.ts，工程agent进一步检查agent.ts与Session/SDK相关逻辑。源码路线不替代真实SDK合同测试。
- [目标WSL环境报告](https://github.com/ruihanzhu5-cyber/agent-orchestration-safety/blob/research/trustfork-environment-audit/docs/dynamic-join/TrustFork_Environment_Report.md)：本轮重读；报告结论只支持离线开发，未声称在当前对话中重新操作用户WSL。
- 现有干净克隆：$HOME/research/trustfork-original-clean-20261024；新开发分支research/trustfork-dynamic-join-offline，从固定作者SHA开始，不从环境报告分支或旧pilot开始。
- 推送目标仅用户现有仓库ruihanzhu5-cyber/agent-orchestration-safety，不创建未知仓库、不推upstream/main、不force push。

## 4. 未完成但不阻塞写代码的验收

| 阶段 | 当前状态 | 必须完成 |
|---|---|---|
| 无API框架实现与自动测试 | 可以开始 | Codex自己写测试、执行、修复；真Pi+脚本模型、真Docker+多原case |
| 真实API预检与smoke | 尚未就绪 | 两别名实际provider/model ID、参数/上下文、目标WSL重检、所跑case任务包与GoalSpec、传感器、冻结/恢复 |
| 全量正式实验 | 尚未就绪 | 30卡覆盖状态、真实H1/H2、smoke成本、评分容量、人工可靠性及确认前冻结 |

未知API值不阻塞离线实现，真实模式必须缺字段即报错。当前不要求用户补第三模型、GPU或Harbor。运行预算仍需实际费用确认，不能因方案列1,664条就宣称预算已足够。

## 5. 发布边界

本轮修改文档与输入合同，未改GitHub实验代码，未在用户电脑运行工具，模型API调用0。完整源代码修改任务见同包Codex指令。文档审核通过不以ASR必须非零为条件；风险机会和观测能力通过工程测试，真实行为结果由后续实验决定。
