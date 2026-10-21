# 原生架构审计：身份 × 交流组织 × 候选人数

本审计先于实验插件开发。基线为官方 `main` 的
`49490514f5187ba4e04b31929f2f4470e0db7def`；首次审计时远端引用与指定 SHA 一致。
工作分支为 `feature/identity-org-native`，在独立工作区从该 SHA 新建。
没有合并或 cherry-pick 旧 Peer、Topology 或 Python Replay 实现。

## 已阅读的原生接口

- `AGENT.md`、`docs/ARCHITECTURE.md`、`docs/BENCHMARK_DESIGN.md`、`docs/SCORING.md`。
- `trustfork/tools/generate_jobs.py`、`trustfork/tools/run_benchmark.py`。
- `trustfork/agents/opencode.py`、`trustfork/scoring/verifier.py`、`trustfork/scoring/aggregate.py`。
- 原始 0451 的 `task.toml`、两个阶段的指令、测试入口及最终 verifier。

## 实际调用链

```text
systems / pool / task private metadata
  -> generate_jobs.resolve_pool / render_display / opencode_roster / job_config
  -> run_benchmark.TaskRunner
  -> harbor jobs start --config
  -> Harbor agent factory / task Docker lifecycle
  -> trustfork.agents.opencode:OpenCode (必须验证实际加载此类)
  -> native opencode 1.18.13 run --agent orchestrator
  -> native task tool / configured child sessions / original workspace tools
  -> OpenCode SQLite + event capture -> adapter ATIF trajectory
  -> hidden task verifier -> reward.json + annotations.json
  -> original aggregate.py
```

0451 有两个不恢复 Main 会话的阶段。第一阶段原测试保存 ATIF 到工作区中的
`.trustfork-harness/trajectories`，第二阶段 verifier 合并跨阶段轨迹。原阶段
指令、文件初态和该原生记忆/快照行为必须保留；不能把第一阶段程序成功退出
等同于攻击成功，也不能把文件存在等同于模型实际读取。

## 不可变边界

`opencode_roster()` 将 Main 的所有工作区工具关闭，仅允许向已列出成员使用
`task`。成员保留原工具，成员 `task` 为 false。仅关闭 `task` 不能证明 shell
无法创建额外 CLI Agent。公开 description 与实际 provider/model 分开配置。
不能把私有目标、评估器信息或真实端点补进公开标签。

基线生成器已经支持 `opencode_plugins`，适配器会安装这些原生插件。
后续仅在 Gate 0 通过后评估最窄的首轮工具返回/会话路由干预；不添加模型 API
循环，不增加 Main 工具，不替换文件操作环境。

## 已确认的兼容性问题

1. 已安装 Harbor 为 0.24.0。其 `AgentFactory.create_agent_from_config()` 在
   `name` 为内置名称时优先于 `import_path`。官方生成器同时输出
   `name: opencode` 与 vendored `import_path`，所以必须核对实际加载的适配器，
   不能仅凭配置中存在 import_path 宣称在使用仓库适配器。
2. 原 verifier 的 `active_actor_map()` 强制 `available_pool_size == 4` 且
   actors 顺序为 A/B/C/D。K=3/6 当前不受支持。不得仅修改 roster 后把原评分
   称为跨规模兼容；在后续 Gate 2 中需单独定义并验证最小推广。
3. 原聚合器汇总八项连续分数，没有单独实现 CAR 列。CAR 的条件分母及扩展事件
   指标需要单独说明，不能把新的判定伪装成已有官方结果。
4. 原 runner 最多三次基础设施无效重试且保留首个有效记录。Gate 0 只安排一次
   诊断尝试，不根据分数或模型建议挑选结果；正式统一重试策略仍须预先冻结。

## Gate 0 当前状态

分支与固定基线检查通过，Docker server 29.8.2、Python 3.12.13 和 Harbor
0.24.0 已响应。后续检查已确认 vendored adapter、原生两阶段 Agent 执行及
子会话轨迹；但原 trajectory Judge 两次输出均未通过原 schema，没有最终八项
评分。最终结论为 Gate 0 NO-GO；未进入插件开发、18 格或 432 条。完整记录见
`docs/IDENTITY_ORG_DELIVERY.md`，不将 Harbor 返回码 0 当作评分成功。
