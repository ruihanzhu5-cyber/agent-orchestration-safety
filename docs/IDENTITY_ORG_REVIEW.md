# 两轮审查：Gate 0 NO-GO 交付

范围：官方基线、原生启动配置、计划表与当次基线执行。
两轮均为本地自查（local-only），不是独立第二位审查者的结论。
未开发实验插件；未审查不存在的实现为 PASS。原生评分未成功，停止扩大。

## Review A：实现正确性

| 项目 | 判断 | 证据与范围 |
|---|---|---|
| 从指定官方提交建立新分支 | PASS | 审计提交的父提交为 4949051，远端 main 同 SHA |
| 未合并、cherry-pick 旧实现 | PASS | 新分支祖先和修改清单；生产源码无改动 |
| 没有新增 Agent Engine | PASS | 仅文档；本地检查脚本调用原生生成器和 Harbor CLI，不调模型 API |
| 使用仓库适配器和原生 OpenCode | PASS | factory 显式 import 路径；原生日志、SQLite、ATIF 和真实子会话 |
| Main 权限与原版一致 | PASS | 原 opencode_roster 配置与实际 Main 工具记录仅 task |
| 任务逻辑、模型未偷偷改动 | PASS | 使用现有外部双模型配置；16 个 0451 文件与上游 blob 字节校验 |
| 初始 Windows 换行可执行 | FAIL → 已定位恢复 | 第一阶段 /tests/test.sh 不能执行；首行 CRLF；精确恢复 LF 后阶段通过 |
| 原生八项评分成功 | FAIL | trajectory Judge 两次原生尝试均失败，没有最终 reward/annotations |
| 回放不是伪造 Agent 输出 | UNCERTAIN / NOT IMPLEMENTED | 本次没有 fixture 或实验插件，不存在可验收实现 |
| Direct/Relay/Discussion 实际路径 | UNCERTAIN / NOT RUN | Gate 0 未通过，未启动协议运行 |
| K=3/4/6 和未知 Agent 审计 | UNCERTAIN | K=3/6 原 verifier 明确拒绝；实际扩展未开发 |
| 18 格与预算 | FAIL / NOT RUN | 前置 Gate 未通过；正式批量付费上限未确认 |

## 逐文件说明

| File | Reason / Before / After | Scientific necessity | Potential confound | Review |
|---|---|---|---|---|
| docs/IDENTITY_ORG_NATIVE_AUDIT.md | 新增原生调用链、Main 权限和兼容性审计；原先无此分支审计 | 在实现前确定边界 | 文档不等于运行证明 | PASS（静态范围） |
| docs/IDENTITY_ORG_DESIGN.md | 新增 18 格、案例筛选和冻结建议约定；原执行不变 | 防止结果驱动改方案 | 12 个仅结构候选，尚未 fixture 审查 | PASS（计划范围） |
| docs/IDENTITY_ORG_REVIEW.md | 新增两轮本地审查和未验证项 | 外部复核索引 | 非独立审稿意见 | local-only |
| docs/IDENTITY_ORG_DELIVERY.md | 新增 NO-GO、失败来源和产物索引 | 不把无评分当安全结果 | 无实验效应数据 | PASS（证据范围） |

本地启动兼容改动只存在于忽略目录：删除内置 name 以选择原 import_path；用原生
TaskConfig 精确选同一个任务；独立输出路径及额外导出原文件快照/判分诊断。
没有修改原生成器、适配器、verifier、任务指令或工具实现。Windows 换行恢复
只恢复 Git 原字节，不提交任务内容差异。原错误轨迹与原 Judge 输出均保留。

## Review B：研究有效性

| 问题 | 判断 | 依据 |
|---|---|---|
| Q1 实际只改变计划因素？ | UNCERTAIN | 因素实验未运行；目前仅基线，启动选择兼容处理已披露 |
| Q2 三种组织是真实交流？ | UNCERTAIN | 未实现/未运行，不能以设计图作证明 |
| Q3 扩大人数未引入能力/权限混杂？ | UNCERTAIN | 固定核心和额外模型已规划，尚未通过 K 验证 |
| Q4 身份确实被对应模型看见？ | UNCERTAIN | 原基线 roster 有描述；扩展可见性审计尚未运行 |
| Q5 Main 决策来自真实模型？ | PASS（基线）/ UNCERTAIN（实验） | 原基线存在 Main task 和实际子会话；没有回放条件数据 |
| Q6 记录 peer 文本变化？ | UNCERTAIN | 协议和数据尚未产生 |
| Q7 原指标保持原语义？ | FAIL / UNCERTAIN | K=4 原 Judge 输出校验失败；K=3/6 当前不兼容 |
| Q8 可能只是框架/Prompt/角色变化？ | UNCERTAIN | 已禁止新 Engine，原生协议尚未实证验证 |
| Q9 是否需要机制消融？ | UNCERTAIN | 尚无主结果，不能事后挑选支持性消融 |
| Q10 无交互可否如实报告？ | PASS（报告规范） | 计划允许无交互，实际没有结果，未填推测数值 |

结论：不能进行正式 Pilot。Gate 0 先解决原判分输出的严格字段一致性并以
版本记录验证，再讨论协议实现。不能把本地两轮自查当作 Gate 1/2/3 已通过。
