# 拓扑分支：入口与解释边界

更新日期：2026-10-21。

本分支 `feature/trustfork-topology-benchmark` 保存较早的固定协作方式探索。
它和从官方代码独立开始的 `feature/peer-chain-evaluation` 是两条工作线。
本分支未合入 Peer-Chain 的横向转述或身份交换实现。

## 已实现

- Original：Main 按原逐成员接口咨询。
- Chain：每次 task 请求调度整队 A → B → C → D，Main 的工具正文收到最后一人的回复。
- Debate：四人先各自回答，再读取冻结的同伴首轮意见并修订；成员仍共享工作区。
- 保存实际子会话、消息边、输出送达与原生评分的适配记录。
- 在 0018 上完成三组探索性运行。后续转向 0451 的 Peer 实验；这不是已经完成的全量拓扑或身份研究。

## 已知限制

1. 三种方式的调用量和委派范围不同。整队参与不能解释成 Main 分别授权了所有人。
2. 模型配置中的 M1 标签一致，不足以证明 Main 实际看到了同一候选名单。旧 replacement task 工具缺少显式 roster 和原生 definition 展示检查，因此身份暴露未经确认。
3. Chain/Debate 的部分过程零分存在评分语义问题，包括将失败的 shell 检查当作有效验证。保留公式和通过 schema 不代表评分结论可靠。
4. 中间回复没有放入 Main 的工具正文，但完整调用信息存在于工具 metadata；是否形成其他可见通道仍需结合原生框架核查。
5. 成员共享文件系统和工具权限，通信图不能代表全部数据流。当前没有实现终端启动新 Agent 的全面隔离；Peer 分支的实际运行已发现这类旁路，不能据此反推本分支已发生同样调用。
6. 三组不具有相同总 token 硬预算；末态未额外导出完整独立工作区快照。不能仅凭现有分数宣称某种拓扑普遍更安全或身份有因果作用。

## 文档与验证

- [设计](TOPOLOGY_DESIGN.md)
- [代码审计](TOPOLOGY_CODE_AUDIT.md)
- [试跑与评分复核](TOPOLOGY_PILOT_REPORT.md)

```bash
python -B -m unittest discover -s tests -p test_topology.py -v
node --test tests/test_topology_runtime.mjs
git diff --check
```

上传前 Python 7/7、Node 4/4 通过。测试验证接口和模拟执行约定，不消除上述实证限制。

原始任务、供应商凭据、个人路径和原始运行上下文保持在本地；仓库只保留源码、离线测试和公开技术说明。
