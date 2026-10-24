# TrustFork 动态入队研究：环境检查报告

检查日期：2026-10-24，Asia/Shanghai（UTC+8）。16:24 为原始资源快照，16:54–17:09 为 Desktop 续查，17:42–18:08 为原生 Docker 安装验收；本轮 Node/Pi 与离线联通验收自 18:27 开始，磁盘收尾快照为 18:56:40。各轮结果分别保留。

**当前结论：Linux Node 24.15.0 / Pi 0.84.1、指定 Python 3.12.13 测试环境、固定原版共享镜像及 Python→真实 Docker CLI 基础调用均已实测可用；最终 6 项 Node SDK 测试、2 项 Python 基础测试和 4 项 Python→Docker 测试全部通过，无跳过。新安装、缓存、镜像与证据位于 D 盘。实验明确不使用 Harbor，其历史未验收不再构成阻塞。已具备开始离线代码开发的基础环境；Pi 完整调度契约和动态实验仍未实现。Pi CLI 自动生成隔离空 auth.json 的文件副作用见 13.4，不能宣称严格零 auth.json 访问。**

本报告保留此前 Part1、Desktop 故障及原生 Engine 安装的历史。用户本轮通过“继续”采用 Node/Pi 环境准备文档，授权固定版本安装、必要测试依赖、固定原版镜像构建及无模型环境验收；不使用 Harbor，不修改实验业务代码、不运行旧 pilot、不读取或复制用户模型密钥、不登录模型、不调用模型 API。PASS / FAIL / UNKNOWN / NOT_RUN 均按具体检查项和时点解释，不把版本、镜像标签或预期错误当作完整实验验收。

**阅读历史的边界：第 1–12 节为此前各轮事实，其中的只读范围、未安装、Harbor 待验收与后续建议属于当时状态；当前范围和准备程度以第 13 节为准。历史 Desktop 故障、旧盘映射 UNKNOWN 保留，不与新原生引擎状态混合。**

## 1. 项目理解

本研究考察 TrustFork 团队中 Main 与老成员 A/B 接纳新人 C/D 时，新人的公开历史履历和当前私有风险目标如何影响交接、委派、建议采用与最终危害。H1、H2、T3 是不同任务；老团队历史拟真实运行生成，新人的 20 条外部履历则是受控合成记录，两者不能混称。后续 PiDynamic 从官方固定提交重新实现，旧 pilot 只作为已有环境事实，不作为实现合同或实验参数的依据。Main 没有工作 shell，四个成员的七个工作工具、peer 通信及评测隔离均留待后续实现和验收，当前不添加防御机制。本轮只检查环境并交付脱敏报告，不训练模型、不续跑旧 pilot，也不进入 Part2。

## 2. 执行位置与检查范围

| 检查 | 状态 | 实际范围与依据 |
|---|---|---|
| Windows 宿主机 | PASS | 本机 Windows 11 家庭版中文版 25H2，10.0.26200.7840，AMD64；PowerShell 7.6.5，初始工作目录 D:\。依据 CIM、注册表与标准库查询；不是只能看到 Linux 隔离容器。 |
| Codex 沙箱差异 | PASS | 沙箱内 CIM 被拒绝，WSL 枚举报 E_ACCESSDENIED；获准的沙箱外只读查询成功。沙箱内 TLS 错误与宿主网络结果分列，不归咎于宿主环境。 |
| Ubuntu-26.04 | PASS | 实际进入已有 Ubuntu 26.04 LTS；内核 6.18.54.1-microsoft-standard-WSL2，x86_64。使用 bash --noprofile --norc，未执行用户启动脚本。 |
| Ubuntu-22.04 | PASS | 实际进入已有 Ubuntu 22.04.5 LTS，同一 WSL2 内核；只读查询资源、版本和安装元数据。 |
| WSL 状态 | PASS | 初次和末次 wsl --list --verbose 均为 Ubuntu-26.04、Ubuntu-22.04、docker-desktop：Stopped，版本 2；检查期间按用户授权短暂启动两套 Ubuntu，未执行 shutdown/terminate。 |
| Docker daemon / 容器内部 | UNKNOWN | 初查 Desktop 未运行；续查按授权启动 Desktop 后发生本地 socket 初始化失败，Linux engine 管道仍不存在。未进入 docker-desktop 或启动容器，无法观察 daemon 内部资源或任务环境。 |
| 安装权限 | UNKNOWN | 初始执行令牌的管理员角色检查为 false；获准执行沙箱外只读查询不等于拥有管理员或安装权限。未用安装或修改设置试探权限。 |

仅在当前工作区浅层定位 TrustFork 仓库，并核对已知 worktree 的虚拟环境元数据；没有遍历整台机器寻找仓库，没有读取旧 pilot 业务实现。公开报告以 {OLD_REPO}、{REPORT_WORKTREE}、{USER}、{WSL_HOME} 代替个人路径和用户名。公开的 GitHub 仓库身份保留用于交接定位。

## 3. 资源、限额和磁盘

| 项目 | 状态 | 实测值 | 命令 / 依据与边界 |
|---|---|---|---|
| 宿主 CPU | PASS | Intel Core i9-13900H，14 物理核、20 逻辑处理器 | Get-CimInstance Win32_Processor，退出码 0。 |
| Windows 进程 CPU 可见性 | PASS | 20 个逻辑处理器，亲和性掩码 1048575 | .NET Environment.ProcessorCount / Process.ProcessorAffinity；额外 Windows 作业对象时间配额 UNKNOWN。 |
| Windows 总物理内存 | PASS | 34,071,240,704 字节，31.731 GiB | CIM 与 GlobalMemoryStatusEx 一致，查询成功。 |
| Windows 当前可用内存 | PASS | 11,378,917,376 字节，10.597 GiB | 16:24:28 快照；较早启动 WSL 前约 12.5–12.9 GiB。不是给实验预留或保证的容量。 |
| Windows pagefile | PASS | 分配 2048 MiB；该次使用 143 MiB、峰值 190 MiB | Win32_PageFileUsage，退出码 0；未把 commit limit 当物理 swap。 |
| WSL CPU | PASS | 两套 Ubuntu 均可见 20 个逻辑 CPU，亲和性计数 20 | os.cpu_count / os.sched_getaffinity。 |
| Ubuntu-26.04 当前 cgroup | PASS | /non-systemd：cpu.max = max 100000，memory.max = max，memory.swap.max = max | 读取当前 cgroup 文件；这一层无额外限额，仍受 WSL VM 资源约束。 |
| Ubuntu-22.04 CPU 配额 | UNKNOWN | 当前层未读到 cpu.max；memory.max、memory.swap.max 均为 max | 未把缺失文件解释为已证实没有 CPU 配额。 |
| WSL VM 内存 | PASS | MemTotal 16,236,420 KiB，约 15.484 GiB；可用约 14.63–14.65 GiB | 两套 Ubuntu 的 /proc/meminfo；与 Windows 物理内存共享，不能相加。 |
| WSL swap | PASS | SwapTotal / SwapFree 均为 4,194,304 KiB，即 4 GiB | /proc/meminfo；swap 后端文件位置 UNKNOWN。 |
| .wslconfig | PASS | networkingMode=mirrored、autoProxy=true、dnsTunneling=true；未见显式 memory/processors/swap 设置 | 仅读取白名单字段；资源以上述运行时值为准。 |
| 当前工作区 D 盘 | PASS | 总 807,072,165,888 字节；可用 657,128,132,608 字节，611.998 GiB | shutil.disk_usage，退出码 0，16:24:28 快照。 |
| C 盘 | PASS | 总 214,749,409,280 字节；可用 6,008,401,920 字节，5.596 GiB | 同一快照；C 盘组件增长和系统余量需另行关注。 |
| Ubuntu-26.04 虚拟文件系统 | PASS | / 总 1,081,101,176,832 字节；一次可用 1,008,347,635,712 字节 | 稀疏 VHDX 内的虚拟容量；后端 D 盘实际余量约 612 GiB，不能视为另有约 1 TB 物理磁盘。 |
| Docker daemon CPU / 内存 / 磁盘 | UNKNOWN | daemon 不可达，无法读取 | 失败 docker info 的零值和空值是失败响应骨架，不是实际资源。 |
| 实验峰值与稳定性 | NOT_RUN | 未启动任务或压力测试 | 不据静态配置宣称实验已能稳定运行。 |
| GPU | NOT_RUN | 未查询 GPU | 远程模型 API 方案不要求本地 GPU，未调整团队成员或团队内并发。 |

初期仍按 1 条独立 trial、约 4 个可用 CPU 核、16 GB 内存、80–100 GB 可用磁盘规划；这是建议，不是实测最低门槛。宿主 CPU 与 D 盘有静态容量余量，WSL 可见内存约 15.5 GiB；Docker 配额、团队并发峰值与稳定性仍未核实。

### WSL 和 Docker 在 D 盘的证据

| 项目 | 状态 | 只读观测 |
|---|---|---|
| Ubuntu-26.04 实际位置 | PASS | 注册目录显示 C:\Users\{USER}\AppData\Local\wsl\{DISTRO_ID}，但该目录是联接，实际指向 D:\WSL\{DISTRO_ID}。ext4.vhdx 文件长度 19,918,749,696 字节。 |
| Ubuntu-22.04 位置 | PASS | 注册目录实际仍在 C:\Users\{USER}\AppData\Local\wsl\{DISTRO_ID}，没有上述联接；VHDX 文件长度 4,532,994,048 字节。其约 1 TB 虚拟文件系统不能突破 C 盘约 5.6 GiB 的当前物理余量。 |
| Docker Desktop 配置 | PASS | CustomWslDistroDir = D:\DockerData\DockerDesktopWSL；IntegratedWslDistros 包含 Ubuntu-26.04；AutoStart=false。配置选中集成不代表运行时集成已可用。 |
| docker-desktop 注册位置 | PASS | D:\docker\wsl\disk\DockerDesktopWSL\main\ext4.vhdx，文件长度 100,663,296 字节。 |
| 已有 Docker 数据文件 | PASS | D:\DockerData\DockerDesktopWSL\disk\docker_data.vhdx：10,831,790,080 字节；D:\docker\wsl\disk\DockerDesktopWSL\disk\docker_data.vhdx：7,492,075,520 字节；D:\docker\wsl\disk\docker_data.vhdx：1,654,652,928 字节。仅查看元数据，未挂载或修改。 |
| 当前有效数据盘映射 / 盘内余量 | UNKNOWN | 多份文件并存，配置路径与注册路径不同；daemon 停止时不足以判断实际使用哪份。文件长度不等于 VHDX 内余量或物理占用，不能据此清理文件。 |

这些证据支持用户所述“此前使用 WSL，Docker 放在 D 盘”的部署背景；不用于推断旧 pilot 的实现正确性。

## 4. 工具、版本与解释器关系

| 层 / 工具 | 状态 | 版本、位置与依据 |
|---|---|---|
| Windows Git | PASS | 2.55.0.windows.1，C:\Program Files\Git\cmd\git.exe；版本查询 0。 |
| Windows 默认 Python | PASS | 3.13.5，C:\Users\{USER}\miniconda3\python.exe，满足 >=3.12；PyYAML 6.0.3、pytest 9.0.1、packaging 25.0，未发现 Harbor 或 pytest-asyncio。 |
| 旧仓库 Windows venv | PASS | {OLD_REPO}/.venv/Scripts/python.exe 为 3.12.13；pyvenv.cfg 明确是 Windows 环境，不能当 Linux venv。仅作为已存在环境事实。 |
| Python launcher 登记项 | FAIL | py -0p 返回的 Python 3.12 登记路径不存在。登记命令退出 0 不证明解释器可启动；机器上另有实际可用 Python。 |
| Windows uv / pip | PASS | uv 0.10.8，用户 .local/bin；默认 python -m pip --version 为 pip 26.0.1、Python 3.13，退出码均 0。 |
| uv tool 枚举 | UNKNOWN | uv tool dir 成功；uv tool list 因既有缓存权限错误退出 2。直接读已知 tools 目录未发现 Harbor tool 环境，不将枚举失败当安装成功。 |
| Windows Node / npm 存在性 | PASS | Node v24.14.0、npm 11.9.0，C:\Program Files\nodejs；版本查询均 0。 |
| Windows Node 与原镜像精确版本 | FAIL | 原镜像指定 24.15.0，宿主是 24.14.0。未升级，未以相近版本代替精确核对。 |
| Windows Pi | FAIL | PATH 无 pi；npm 全局前缀 D:\npm-global 的 node_modules 不存在；当前前缀、Node 标准安装目录、用户 npm 默认目录及旧仓库 node_modules 均未找到 Pi 包。结论限于所查范围。 |
| Windows Harbor CLI | PASS | PATH 无 harbor，但 {OLD_REPO}/.venv/Scripts/harbor.exe --version 返回 0.24.0，退出 0。不是全局 CLI 已配置。 |
| 旧 venv Harbor 导入路径 | PASS | Harbor 0.24.0；原 Pi 适配器所需 Harbor 模块及导入符号逐一核对，缺失符号为 0；packaging 26.3、PyYAML 6.0.3。没有导入、实例化项目 agent 或运行原适配器。 |
| 默认 Python 的 Harbor | FAIL | 默认 Conda Python 的 Harbor 元数据 / import spec 不存在。旧 venv CLI 可用不代表默认解释器可导入。 |
| 旧 venv 测试依赖 | FAIL | 未发现 pytest、pytest-asyncio；最终是否需要这些包由后续测试方案决定，本轮未安装。 |
| Ubuntu-26.04 系统 Python / Git | PASS | /usr/bin/python3 为 3.14.4，满足 >=3.12；/usr/bin/git 为 2.53.0。未验证研究依赖对 Python 3.14 的完整兼容性。 |
| Ubuntu-26.04 Linux Python 3.12 | PASS | {WSL_HOME}/.local/bin/python3.12 指向 uv 管理的 Linux CPython 3.12.13；直接版本查询 0。该解释器中无 Harbor、pytest、pytest-asyncio、PyYAML、packaging。 |
| Ubuntu-26.04 Linux uv | PASS | {WSL_HOME}/.local/bin/uv --version 为 0.12.1，退出 0；在非登录 shell PATH 外，不能单凭 command -v 断言未安装。 |
| Ubuntu-26.04 Linux Node / Pi | FAIL | PATH、所查用户和系统标准安装位置、D 盘所查 TrustFork 环境中未找到可用 Node / Pi；用户 nvm 目录不存在。npm 来自 /mnt/c/Program Files/nodejs/npm，不能把其版本当成 Linux Node 已就绪。 |
| D 盘已有 TrustFork Linux venv | PASS | D:\envs\trustfork-linux，即 /mnt/d/envs/trustfork-linux；不是 worktree 内的 .venv。直接运行其 bin/python 成功，实际 Python 3.12.13，prefix 对应此目录，链接最终指向现有 uv 管理的 Linux Python；不是用别的解释器替代后宣称原环境通过。 |
| Linux venv Harbor CLI / 依赖导入 | PASS | /mnt/d/envs/trustfork-linux/bin/harbor --version 返回 0.24.0、退出 0；同一 bin/python 可导入原 Pi 适配器所需 Harbor 模块和全部导入符号，缺失符号 0；PyYAML 6.0.3、packaging 26.3，fcntl 可用。未导入或实例化项目 agent。 |
| Linux venv 测试依赖 | FAIL | 该环境没有 pytest、pytest-asyncio；这不影响已完成的版本 / 已知库导入检查，后续是否需要安装由具体测试方案决定。 |
| D 盘其他同名工具环境 | FAIL | D:\envs\trustfork-tools\harbor 的 pyvenv.cfg 指向 Windows Python；存在 Scripts/python.exe，但没有 Harbor CLI 或包元数据，不是可用 Linux 环境，也不作为 Harbor 已安装的依据。 |
| 已知 worktree 内环境 | PASS | 旧主工作区 .venv 是 Windows 环境，其他三个已知 worktree 未发现 venv；本轮未创建环境。D 盘已有 Linux 环境和原工作区的 Windows .venv 分开记录。 |
| Ubuntu-22.04 默认 Python | FAIL | Python 3.10.12 不满足 >=3.12；Git 2.34.1。没有更改系统 Python。 |
| Ubuntu-22.04 Node / Pi / Harbor | FAIL | 默认 PATH 与所查标准安装位置未找到；未拿 Windows npm 转接脚本替代。 |
| Windows Docker / Compose | PASS | Client 29.8.2、API 1.56、windows/amd64；Compose v5.6.0；CLI 位于用户 Docker Desktop 安装目录，context=desktop-linux。 |
| Windows Docker daemon | FAIL | 初查未启动；续查 docker desktop start --detach --timeout 30 退出 0，并出现 Desktop/backend 进程，但恢复旧更新提示后在 sailor-ingest.sock 初始化失败。最终 docker version / info / image ls 仍退出 1，dockerDesktopLinuxEngine 管道不存在；启动命令成功不代表 engine 可用。 |
| WSL Docker 运行时集成 | FAIL | 两套 Ubuntu 的 docker 都落到 Windows Desktop 转接脚本，退出 1，提示当前 WSL 集成不可用；无 /var/run/docker.sock。Ubuntu-26.04 的原生服务 is-active / is-enabled 均退出 4；Ubuntu-22.04 为 3/1，没有可用原生 docker.service。 |
| 已有镜像 / 镜像内 Pi | UNKNOWN | daemon 不可达，镜像枚举失败，不能声称目标镜像存在或缺失；未运行镜像检查内部版本。 |

Windows 默认 Python、旧 Windows venv、WSL 系统 Python、WSL 管理的 Python 3.12，以及 D 盘已有 Linux venv 是不同环境。Harbor 0.24.0 已分别在旧 Windows venv 和 /mnt/d/envs/trustfork-linux 完成版本与有限依赖符号核对，不能由此推出容器生命周期或 Pi SDK 契约已验收。Linux 工具没有进入默认非登录 PATH，早期仅看 PATH 的暂定判断已在本报告中纠正。

## 5. 仓库、官方基线及报告分支

| 概念 / 检查 | 状态 | 实际值与证据 |
|---|---|---|
| 初始 D:\ | PASS | git rev-parse --show-toplevel 退出 128，驱动器根不是仓库；随后在当前工作区内定位到 {OLD_REPO}。 |
| 用户原工作区当前分支 | PASS | feature/trustfork-topology-benchmark，未切换。 |
| 原工作区 HEAD | PASS | ff1d6084d95b7a246c4c58f4da516c3f65a761ad。 |
| 原工作区改动 | PASS | 初始 6 个 untracked 状态条目：.aris/、.gitattributes、MANIFEST.md、refine-logs/、tests/test_reference_repeat.py、trustfork/tools/run_reference_repeat.py。后续复核分支、HEAD 和状态清单一致，未读取这些业务文件。 |
| 原有其他 worktree | PASS | feature/identity-org-native @ a55363ec65485e1d1b391510ba0254b88d7757bd；feature/0451-identity-replay @ 29fe1d0fb51520362403845a7d3ce878a00bcc00；feature/peer-chain-evaluation @ e1d2556701f194c13c376bf42f921a05c04be5a6；未切换或修改。 |
| 官方原实验仓库 | PASS | henrymao2004/agent-orchestration-safety；已有 upstream URL 与官方 HTTPS URL 一致；仅供基线核对，不是报告推送目标。 |
| 官方原实验分支 | PASS | GitHub 官方 branches/main 的实际 HEAD 为 49490514f5187ba4e04b31929f2f4470e0db7def。连接器读取不作为本机网络测试。 |
| 固定提交本地可得 | PASS | cat-file -t 返回 commit；本地 main、origin/main、upstream/main 均指向固定 SHA；merge-base --is-ancestor BASE upstream/main 退出 0；无需 fetch。 |
| 用户报告目标仓库 | PASS | ruihanzhu5-cyber/agent-orchestration-safety，公开仓库；已核对认证账号归属、push 权限和 origin 的 push URL。未改可见性或 origin。 |
| 同名报告分支冲突检查 | PASS | 原先本地不存在；GitHub 分支查询为空；ls-remote --exit-code --heads origin refs/heads/research/trustfork-environment-audit 退出 2，无匹配。 |
| 本次报告分支 / worktree | PASS | 独立创建 research/trustfork-environment-audit；初始 HEAD 恰好为固定 SHA，初始状态干净；没有从 pilot HEAD 分叉。 |
| 报告提交范围 | PASS | 仅授权 docs/dynamic-join/TrustFork_Environment_Report.md；提交前检查 staged paths、空白、敏感信息和相对基线差异。最终提交 SHA 与远程核验放在最终回复，避免自引用。 |
| 后续代码开发分支 | NOT_RUN | 计划 research/trustfork-dynamic-join-offline；本次本地 ref 查询退出 1、尚不存在，未创建；将来应另从固定 SHA 建立。 |
| Git 身份 / hooks | PASS | 已配置 user.name、user.email、credential helper，只检查存在性；未发现自定义 hooksPath 或非 sample hooks，未改全局配置。 |

Git 只读查询均使用 GIT_OPTIONAL_LOCKS=0。报告 worktree 首次创建在沙箱内因 refs 写权限失败（255），确认没有产生分支或占用目录后，在授权的沙箱外重试成功（0）。报告目录写入也需沙箱外权限，均限于报告交付；没有删除、覆盖或 reset 既有分支。

### 固定基线环境合同

只用 git show 49490514f5187ba4e04b31929f2f4470e0db7def:路径读取 AGENT.md、README.md、docs/REPRODUCIBILITY.md、pyproject.toml、trustfork/base-image/Dockerfile、trustfork/tools/ensure_base_image.py、trustfork/tasks/indirect/trustfork_0001/task.toml，均退出 0；Pi 适配器只读导入和类定义附近内容，未执行文中命令。

| 原基线事实 | 状态 | 结果与含义 |
|---|---|---|
| Python / Harbor 要求 | PASS | requires-python >=3.12，直接依赖 PyYAML >=6.0；原仓库没有锁定唯一 Harbor 版本。 |
| 原镜像版本 | PASS | Python 3.12-slim、Node 24.15.0、Pi 0.84.1、@tintinweb/pi-subagents@0.15.0；Pi 主包 @earendil-works/pi-coding-agent。仅为源文件声明，非镜像实测。 |
| 原镜像标签 | PASS | trustfork-agents:tf-three-harnesses-v1；未拉取或构建。 |
| 原构建脚本平台依赖 | FAIL | ensure_base_image.py 顶层导入 fcntl，原生 Windows find_spec 为 None，不能在 Windows Python 中直接照跑；WSL/Linux 可作为后续部署方向，脚本未执行。 |
| 首条集成候选资源 | PASS | trustfork_0001/task.toml：2 CPU、4096 MB 内存、10240 MB 存储、0 GPU；build、agent、verifier 超时各 1200 秒。部署编号 trustfork_0001 与方案中原场景卡 10053 分列，未读攻击资产核验映射。 |
| 新模型方案与原配置 | UNKNOWN | 原 agent allowlist 为 api.z.ai / api.minimaxi.com，verifier 为 api.deepseek.com；原 README 默认 judge 不等于拟用 GPT-4o。后续须明确 endpoint、准确模型 ID、allowlist 和独立 judge 适配，本轮未改配置。 |

原始证据：[固定 pyproject](https://github.com/henrymao2004/agent-orchestration-safety/blob/49490514f5187ba4e04b31929f2f4470e0db7def/pyproject.toml)、[Dockerfile](https://github.com/henrymao2004/agent-orchestration-safety/blob/49490514f5187ba4e04b31929f2f4470e0db7def/trustfork/base-image/Dockerfile)、[构建脚本](https://github.com/henrymao2004/agent-orchestration-safety/blob/49490514f5187ba4e04b31929f2f4470e0db7def/trustfork/tools/ensure_base_image.py)、[候选 task 配置](https://github.com/henrymao2004/agent-orchestration-safety/blob/49490514f5187ba4e04b31929f2f4470e0db7def/trustfork/tasks/indirect/trustfork_0001/task.toml)。

## 6. 网络与代理

Windows 宿主使用 curl.exe --disable --head --connect-timeout 5 --max-time 12，保持 TLS 校验；WSL 使用 Python 标准库默认 CA 校验的 HEAD 请求，超时 8 秒。公开服务探针没有发送凭据、关闭 TLS 校验或调用模型接口。

| 目标 | 层 | 状态 | DNS / HTTPS 结果、退出码 |
|---|---|---|---|
| github.com | Windows 宿主 | PASS | DNS 0；HTTP 200、curl 0、TLS verify 0。 |
| pypi.org | Windows 宿主 | PASS | DNS 0；HTTP 200、curl 0、TLS verify 0。 |
| registry.npmjs.org | Windows 宿主 | PASS | DNS 0；HTTP 200、curl 0、TLS verify 0。 |
| registry-1.docker.io/v2/ | Windows 宿主 | PASS | DNS 0；HTTP 401、curl 0、TLS verify 0；请求到达未认证 Registry，不等于已能拉镜像。 |
| 同上四个目标 | Windows Codex 沙箱 | UNKNOWN | DNS 成功；curl 均退出 35：schannel AcquireCredentialsHandle / SEC_E_NO_CREDENTIALS，HTTP 000；是该执行上下文 TLS 查询受限，非宿主断网或缺模型 key 的证据。 |
| github.com | Ubuntu-26.04 WSL2 | PASS | DNS 成功；HTTP 200；探针 0。 |
| pypi.org | Ubuntu-26.04 WSL2 | PASS | DNS 成功；HTTP 200；探针 0。 |
| registry.npmjs.org | Ubuntu-26.04 WSL2 | PASS | DNS 成功；HTTP 200；探针 0。 |
| registry-1.docker.io/v2/ | Ubuntu-26.04 WSL2 | PASS | DNS 成功；HTTP 401；收到 HTTPError 响应，探针按“已收到 HTTP”记 0，未将 401 当断网。 |
| Ubuntu-22.04 外网 | WSL2 | NOT_RUN | 没有重复执行外网探针，不外推另一发行版的结果。 |
| daemon 拉镜像网络 | Docker daemon | NOT_RUN | daemon 不可达，未拉取镜像。 |
| 容器网络 / mock 服务 | 容器 | NOT_RUN | 未启动容器或服务。 |
| 被测模型 / judge API | 全部层 | NOT_RUN | endpoint、准确模型 ID、兼容性和 judge 容量均留待后续；没有要求或检查 API key。 |

代理仅记录存在性、协议、loopback、端口及是否带认证。Windows / WSL 的 HTTP(S) 代理为 loopback 7890，未带认证；Windows 沙箱另有 loopback 9 的 ALL_PROXY 标志，WSL 未见该项。未输出 NO_PROXY 内容、私有 IP 或密码，也未修改 shell、WSL、Docker、Clash 配置。Docker 未见 DOCKER_HOST/DOCKER_CONTEXT 环境覆盖，配置 currentContext=desktop-linux；daemon 实际代理 UNKNOWN。Git 报告交付使用既有认证，与无认证网络探针分开。

## 7. 问题清单与后续准备建议

以下只提出建议，本轮未修复。

| 问题 | 状态 | 影响 | 后续建议 / 用户操作 |
|---|---|---|---|
| Desktop 本地 socket 初始化失败，daemon / WSL 转接不可用 | FAIL | 阻塞 Docker / Harbor 集成，不阻塞无 Docker 的单测准备 | 本轮已授权并尝试启动，实际失败在 Windows 运行时 socket，详见第 11 节。后续环境准备需先解决该障碍再核实 daemon；本轮不清理、重置或重装，也没有证据证明重启一定解决。 |
| 多份 D 盘 Docker VHDX，映射未确认 | UNKNOWN | 数据保留、镜像可见性及磁盘容量 | daemon 恢复后确认实际数据路径；不按名字或文件大小判断可删文件，不迁移或清理。 |
| 新实现的 Linux 环境选择与依赖固定 | UNKNOWN | 影响后续测试的可重复性 | 已有 /mnt/d/envs/trustfork-linux 可运行 Python 3.12.13、Harbor 0.24.0、PyYAML 6.0.3，不能再报告为缺 Linux Harbor。后续明确复用还是建立独立环境、记录版本和配置 PATH；pytest 等按实际测试要求补齐，不因它来自旧工作而认定实现正确。 |
| Linux Node / Pi 未找到；宿主 Node 不等于原精确版本 | FAIL | 阻塞 Pi SDK 契约测试 | 后续确定 Node 使用范围及 Pi 0.84.1 位置、来源，不把 Windows npm 当 Linux Node。 |
| Harbor 的完整集成兼容性 | UNKNOWN | Docker 集成与后续调度适配 | Windows 和 Linux 既有环境均有 0.24.0，有限导入已核对；后续先恢复 daemon，再测试实际生命周期与适配合同。原基线没有唯一 Harbor 锁版本，不自动升级或重装。 |
| 原构建脚本用 fcntl | FAIL | 阻塞原脚本在原生 Windows Python 中直接运行 | 明确 WSL/Linux 部署方向，不为让预检通过而改脚本或添加替代实现。 |
| C 盘仅约 5.6 GiB 可用 | UNKNOWN | 系统余量、C 盘 Ubuntu-22.04 的 VHDX 增长 | 主候选 Ubuntu-26.04 和 Docker 文件已在 D 盘；后续关注 C 盘余量，本轮不清理或搬移。 |
| Python launcher 失效登记 | FAIL | py 选择解释器可能失败 | 使用已核实的解释器路径；另获授权后再修复登记。 |
| 模型 / judge / allowlist 未适配 | UNKNOWN | 真实 API 实验与评分 | 另行明确 GPT-4o、用户所指 DeepSeek Flash 的准确 endpoint / model ID、judge 与凭据隔离，不猜 ID，不继承原默认 judge。 |
| 隔离、调度、七工具、冻结恢复、峰值未验收 | NOT_RUN | 实验有效性与稳定性 | 代码和无 API 验收需后续授权，最后才做真实 API 小规模验收，本轮不补实现。 |

下一阶段用户先核对报告并确定运行位置；若选择 Ubuntu-26.04，可另行授权环境准备。专用环境、软件安装、PATH、Docker 启动与路径核实可在明确授权后由 Codex 执行；需要交互或权限时再依实际提示处理。本轮不要求提供 API key。

## 8. 准备程度分别判断

| 类别 | 环境前提状态 | 判断 / 实际测试状态 |
|---|---|---|
| 纯 Python 测试 | UNKNOWN | 已有可用 Linux Python 3.12 / PyYAML / Harbor 环境，也有 Windows Python；新实现的具体测试依赖尚未确定，Linux venv 未装 pytest。基本运行前提有基础，测试本身 NOT_RUN。 |
| Pi SDK 契约测试 | FAIL | 所查范围没有可用 Pi 0.84.1 SDK，Linux Node 未准备；完整 turn 调度交还、持久会话和中断语义均 NOT_RUN。 |
| Docker / Harbor 集成 | FAIL | Windows 与已有 Linux venv 的 Harbor 有限版本 / 导入已核对；本轮启动 Desktop 后仍因本地 socket 错误无法连到 daemon。容器、镜像内 Pi、mock 服务、七工具、冻结恢复均 NOT_RUN。 |
| 真实 API 实验 | NOT_RUN | 本阶段不执行，完整集成前提也未验证；模型、judge、私有信息隔离均未验收，不能宣称正式实验可直接运行。 |

## 9. 本次操作边界与限制

| 操作 | 状态 | 实际情况 |
|---|---|---|
| 安装 / 升级软件或包，创建 venv，更新锁文件 | NOT_RUN | 全部未执行。 |
| 拉 / 构建镜像，运行 / 修改任务容器 | NOT_RUN | 全部未执行；没有 docker run、docker start、compose up、pull 或 build。 |
| 启动已安装的 Docker Desktop | PASS | 续查按用户明确授权执行 start，未执行 update / installer / reset；GUI 与 backend 进程启动，但 Linux daemon 初始化失败，详见第 11 节。 |
| 启动已有 Ubuntu | PASS | 用户补充授权后短暂进入两套已有 Ubuntu；未手动启动其中服务，末次均 Stopped。属于本次获准的状态变化。 |
| 修改实验代码、配置、任务资产或旧 pilot | NOT_RUN | 全部未执行；新 worktree 只检出原基线，源文件内容未改。 |
| 调用实验模型、judge、benchmark | NOT_RUN | 全部未执行。 |
| Git 报告交付 | PASS | 第一轮建立独立报告 worktree；本轮沿用同一 research/trustfork-environment-audit 分支及同一报告文件，只追加报告提交、正常推送；不建代码开发分支、PR，不合并或强推，不切换原工作区。 |
| 公开凭据或原始日志 | NOT_RUN | 未读 .env、未输出完整环境变量、token、代理密码；只提交脱敏总结，不提交探针或原始日志。 |

uv tool list 曾尝试初始化既有缓存并因权限拒绝退出 2；未安装包，未把它当完整枚举成功。不能仅凭退出码证明没有任何缓存元数据尝试，在此如实记录。个别探针最初有输出编码或 PowerShell 参数构造错误，已纠正重试；这些错误不作为缺软件或资源不足的证据。没有执行仓库未知脚本。

## 10. 交接与简短答案

- **实际检查的是哪里？** 用户 Windows 宿主机及获准进入的两套 Ubuntu WSL2；不是只有 Codex 隔离容器。daemon 与容器内部仍不可见。
- **CPU / 内存 / 磁盘是多少？** 宿主 14 核 / 20 线程、31.731 GiB 物理内存，主快照可用 10.597 GiB；D 盘可用 611.998 GiB，C 盘 5.596 GiB；WSL 约 15.484 GiB 内存和 4 GiB swap。均为观测值；Docker 配额 / 盘内余量 UNKNOWN，虚拟容量不等于物理容量。
- **Docker 当前状态？** Client 29.8.2、Compose 5.6.0 已安装；续查已启动 Desktop，但 Windows 本地 socket 初始化失败，Linux daemon 仍不可达，WSL 转接不可用；容器功能 NOT_RUN。资源和镜像内容仍无法取得，不能写成 0 或空清单。
- **Pi / Harbor 及环境对应？** 所查范围未找到 Pi；Harbor 0.24.0 同时存在于旧 Windows venv 和 /mnt/d/envs/trustfork-linux，两边版本及有限依赖符号核对成功。默认系统解释器没有 Harbor，不代表 Linux 环境没安装；应使用对应 venv 的解释器与 CLI。
- **当前分支 / 固定基线 / 后续分支？** 原分支 feature/trustfork-topology-benchmark @ ff1d6084d95b7a246c4c58f4da516c3f65a761ad 保留；固定 SHA 本地存在并经官方 main 核对；报告分支从 49490514f5187ba4e04b31929f2f4470e0db7def 独立建立，未来 research/trustfork-dynamic-join-offline 也须另从该 SHA 创建，本次未创建。
- **下一阶段先做什么？** 用户审阅后明确环境准备授权；候选仍为 Ubuntu-26.04 及已有 /mnt/d/envs/trustfork-linux。首先处理 Desktop 的运行时 socket 启动障碍，再核实 WSL 集成、数据盘和镜像，随后准备 Node / Pi 与测试依赖；本轮不提供修复性删除、迁移或重装。
- **还有什么没测？** 镜像实际内容、Pi SDK 调度和会话语义、Harbor 生命周期、七工具保真、peer 通信、私有信息隔离、mock 服务、冻结恢复、峰值稳定性、模型兼容性及 judge 容量均未测试。

真实仓库、最终 commit SHA、push 验证和固定提交文件链接由最终回复给出。报告交付后停止，等待下一条明确指令；报告审阅通过不自动授权安装、建代码开发分支或改实验代码。受限及未执行项目已分别标注，不能宣称全部环境验收通过。

## 11. Docker Desktop 启动后续查（2026-10-24）

本节是本轮新增证据，范围为启动已安装的 Desktop、进入已有 Ubuntu-26.04、只读查询 Linux daemon / WSL 集成 / 资源 / 数据盘 / 镜像。沿用原报告分支，不进入 Part2。

### 11.1 启动经过与两个错误

| 时间（Asia/Shanghai） | 状态 | 实际事件与依据 |
|---|---|---|
| 16:55 | PASS | 启动前核对原报告分支远程 HEAD 与本地一致；Desktop status 退出 1、当前不可用。 |
| 16:56:19 起 | PASS | docker desktop start --detach --timeout 30 退出 0，输出 Starting Docker Desktop；16:56:20–26 出现 Desktop 和 backend 进程。这只证明启动请求和进程存在。 |
| 16:56:24 | FAIL | 本地 backend 日志：CheckForInstallerErr: previous update failed (Failed to apply delta update), showing recovery dialog。今天启动读取到旧更新失败状态，不是本轮执行更新命令。 |
| 恢复弹窗处理 | PASS | 用户确认已点击 Continue，以恢复的现有版本继续启动。代理未执行安装器、update 或下载 / 安装新版。 |
| 17:03:13–18 | FAIL | 后台在 starting services / initializing Ingest server 阶段失败：把 sailor-ingest.sock 重命名为 sailor-ingest.sock.stale 时，系统返回 The file cannot be accessed by the system；随后 backend crashed。 |
| 17:07:50 | FAIL | 宿主沙箱外 os.lstat / os.stat 对该 socket 均报 WinError 1920；不是仅有沙箱内失败。父目录可读、归当前用户、未见 deny ACE；socket 自身 ACL 读取失败，具体文件状态 / 锁定 / 权限根因仍 UNKNOWN。 |
| 17:09 收尾 | FAIL | docker version 和 image ls 仍退出 1，Linux engine 命名管道不存在。WSL 列表显示 Ubuntu-26.04、Ubuntu-22.04、docker-desktop 均为 Stopped；没有可用 daemon。 |

旧更新问题的只读证据：10 月 22 日 updater 日志记录 4.95.0（242831）到 4.96.2（244353）的更新尝试、安装器失败退出；对应 installer 日志出现 No installation found。更早的成功安装记录是 per-user 安装。这个组合提示旧更新可能存在安装识别问题，但不足以把完整根因写成确定结论；本轮没有重新执行升级，也未将 C 盘余量或某个 VHDX 大小当作该错误的原因。运行日志仍标识 Docker Desktop 4.95.0。

原始证据均只读查看：Docker 本地 host backend / updater 日志、install-log.0.txt / install-log.1.txt 等安装日志，以及用户提供的两次弹窗。只在报告保留脱敏摘录，不提交原始日志、截图、会话标识或诊断包。[Docker 官方 CLI 文档](https://docs.docker.com/desktop/features/desktop-cli/)也将 start 和 update 列为不同命令。

### 11.2 用户要求的运行项目

| 检查项 | 状态 | 结果、命令与退出码 |
|---|---|---|
| 已安装 Desktop 的启动请求 | PASS | start --detach --timeout 30：0；GUI / backend 进程存在。启动成功与 engine ready 分开判断。 |
| Linux daemon 可达性 | FAIL | Windows docker version / info：1，Server=null，dockerDesktopLinuxEngine 管道不存在；恢复弹窗后 8 次版本就绪查询均为 1。后续已取得明确启动失败日志，没有把反复重试当修复。 |
| 配置中的 Ubuntu-26.04 集成 | PASS | settings-store.json 的 IntegratedWslDistros 包含 Ubuntu-26.04，AutoStart=false，SettingsVersion=46；续查后这些字段与此前相同。 |
| WSL 实际连接可用性 | FAIL | 已进入 Ubuntu-26.04：docker 仍是 Windows Desktop 转接脚本，版本 / info / context 均退出 1；/var/run/docker.sock 不存在。当前不能连接，不据此认定集成配置丢失或应在 Ubuntu 另装 daemon。 |
| 正常 daemon 下的 WSL 集成是否生效 | UNKNOWN | Desktop 在本地服务初始化阶段失败，尚无正常运行的 engine / 挂载可供检验。没有取得 Windows 与 WSL 指向同一 daemon 的运行证据。 |
| daemon 类型 / Server 版本 | UNKNOWN | 客户端 context=desktop-linux 仅为配置；Server 不可达，不能把客户端的 windows/amd64 当 Linux Server 的类型或版本。 |
| daemon CPU / 内存额度 | UNKNOWN | info 失败；输出中的 NCPU=0、MemTotal=0 为失败响应，不是配额。不得用宿主 20 线程或 Ubuntu 约 15.5 GiB 替代 daemon 实测。 |
| daemon DockerRootDir / 盘内余量 | UNKNOWN | 无法读取；没有用 D 盘物理余量、VHDX 文件长度或 1 TiB 虚拟上限代替 daemon 存储容量。 |
| 现有镜像清单 | UNKNOWN | docker image ls --no-trunc --digests --format JSON：1，engine 管道不存在；不是“0 个镜像”或“没有目标镜像”。无可验证镜像条目可列。 |
| 目标镜像 / 镜像内部 Pi | UNKNOWN | 无法读取镜像元数据，未运行镜像或容器来验收；不继承旧 pilot 的镜像假设。 |
| 容器功能、mock、Harbor 生命周期、Pi 契约 | NOT_RUN | 本轮未运行容器、任务、已有实验脚本或模型 API；只读连接查询未代替集成测试。 |

### 11.3 多份 D 盘 VHDX 的证据链

用户要求根据运行状态确定实际数据盘。本轮采用 Desktop 配置、WSL 注册位置、Windows Get-DiskImage 附加状态和启动日志交叉核对，没有以文件名、长度或修改时间作选择依据。

| 路径 | 查询状态 | Get-DiskImage 运行观测（约 16:58） | 可支持的结论 |
|---|---|---|---|
| D:\DockerData\DockerDesktopWSL\disk\docker_data.vhdx | PASS | Attached=false，退出 0 | 是 Desktop 配置目录下的现有文件，该时点未附加；不能宣称当前 daemon 正在使用。 |
| D:\docker\wsl\disk\DockerDesktopWSL\disk\docker_data.vhdx | UNKNOWN | CIM 返回 Access denied，退出 1 | 无法取得附加状态；权限错误不等于“正在使用”，也不等于“可删除”。 |
| D:\docker\wsl\disk\docker_data.vhdx | PASS | Attached=false，退出 0 | 该时点未附加；不根据大小认定是旧盘或应清理。 |
| D:\docker\wsl\disk\DockerDesktopWSL\main\ext4.vhdx | PASS | Attached=false，退出 0 | 与此前 docker-desktop 注册目录一致，但不是 daemon 数据盘映射已核实的证据。 |
| 实际使用的 daemon 数据 VHDX | UNKNOWN | Linux daemon 启动失败，没有运行时 mount / DockerRootDir 及宿主文件映射 | 当前无法确定使用哪份；保留 UNKNOWN，禁止选取配置值或文件大小“补齐”答案。 |

配置仍为 CustomWslDistroDir = D:\DockerData\DockerDesktopWSL；此前注册的 docker-desktop 目录仍是 D:\docker\wsl\disk\DockerDesktopWSL\main。两者是不同种类的证据，不能直接视为同一数据目录。恢复 daemon 后才适合继续核对实际挂载与路径关系，本轮没有通过手动挂载 VHDX 来替代该验证。

### 11.4 副作用、权限限制及交接

- **Desktop 自身的运行时文件处理：** 17:03:13 日志记录它将旧运行时 socket 目录放到 C:\Users\{USER}\AppData\Local\Docker\run.stale\20261024-090313.550。只读目录检查确认该目录存在，含四个运行时条目，包括 sailor-ingest.sock；原路径处的 socket 仍不可访问。此为 Desktop 启动中发生的自动状态变化，不能声称启动没有文件系统副作用。代理没有手动删除、重命名、迁移或清理这些条目，更没有处理 D 盘 VHDX、镜像或任务数据。
- **桌面控制：** 用户明确授权接管必要点击后，已读取并初始化 computer-use；窗口枚举成功，但绑定 / 读取 Docker Desktop 窗口被工具权限检查拒绝，返回 Computer Use was not approved to use Docker Desktop。实际没有代理 UI 点击；未绕过该限制使用其他 Windows UI 自动化。此前 Continue 由用户完成。
- **操作边界：** 没有安装或升级、pull / build、docker run / start、compose up、任务容器、数据迁移 / 清理、factory reset、实验代码修改或模型 API 调用；没有点击诊断采集 / 上传。没有为绕过 socket 错误改权限、改安全设置或修改 Docker 配置。
- **准备程度：** Docker / Harbor 集成仍为 FAIL；daemon 额度、镜像和当前数据盘为 UNKNOWN；Pi SDK、七工具、冻结恢复及真实 API 为 NOT_RUN。旧 Python / Harbor 有限导入证据保持有效，但不能据此宣称 Docker 集成就绪。
- **后续建议：** 将本地 socket 启动障碍列为环境准备阶段的首个问题；具体修复方案需另行明确范围。本轮不因启动失败自动清理 socket、重置 Desktop、重装或升级。若恢复 daemon，再继续只读核实额度、当前数据盘、WSL 同一 daemon 身份和镜像清单。
- **Git 交付：** 同一 docs/dynamic-join/TrustFork_Environment_Report.md、同一 research/trustfork-environment-audit 分支，仅提交报告，正常推送，不强推。旧工作区保持原分支 / HEAD 和原有 6 个 untracked 状态条目；未进入 Part2。

## 12. WSL 原生 Docker Engine 安装与验收（2026-10-24）

### 12.1 授权、起点与方案选择

用户明确采用 D 盘 WSL 原生 Engine 方案。17:42 查询远端 research/trustfork-environment-audit，仍为 4c264aa74b472e08c0191a85972f62801106796b；独立报告 worktree 干净，未切换旧 pilot。Ubuntu-22.04 与 docker-desktop 均停止，只进入已有 Ubuntu-26.04。Windows 当前令牌不是管理员，Linux sudo -n true 返回 1；正常的 wsl -d Ubuntu-26.04 -u root 管理入口返回 uid=0，因此本轮 Linux 安装不需要索要 sudo 密码或 Windows UAC。

实测发行版是 Ubuntu 26.04 LTS / resolute / amd64，内核 6.18.54.1-microsoft-standard-WSL2；PID 1 为 systemd，is-system-running 返回 running。现有 /etc/wsl.conf 已包含 systemd=true，本轮未修改它。安装前没有列出的冲突包，也没有 Docker / containerd 数据目录。仅有系统服务和本次检查进程，没有其他发行版或无关用户任务需要避让。

Docker 当前官方安装页明确支持 Ubuntu 26.04，使用该发行版自己的 resolute/stable 仓库；没有借用其他 Ubuntu 代号、运行 convenience script 或全系统升级。安装方法依据 [Docker Ubuntu 官方安装页](https://docs.docker.com/engine/install/ubuntu/)；WSL 服务管理依据 [Microsoft systemd 说明](https://learn.microsoft.com/en-us/windows/wsl/systemd)。

旧 Desktop 的 sailor-ingest.sock 故障仍是历史事实。此前进一步只读枚举见 socket 的属性为 0x420，重解析标签为 0x80000023（AF_UNIX），以 OPEN_REPARSE_POINT 尝试只读打开仍返回 1920；普通 run 目录本身不是重解析点。标签表示 Unix socket，不能单凭该标签或 fsutil 的失败认定文件损坏。相关错误在 Docker 官方仓库的 [issue 676](https://github.com/docker/desktop-feedback/issues/676) 及 [issue 554](https://github.com/docker/desktop-feedback/issues/554) 有报告；维护者称较新版本包含缓解，但本机 4.95.0 仍失败，不能据此证明本机底层原因或保证升级能解决。更底层的 NTFS、过滤驱动、更新回滚或权限原因仍为 UNKNOWN，未完成占用句柄排查。标签含义见 [Microsoft 重解析标签表](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/c8e77b37-3909-4fe6-a4ea-2b9d423b1ee4)。

按本次新范围，不再执行 socket 修复；没有手动删除或重命名旧 socket / 其目录、修改整棵 ACL、恢复出厂、注销发行版或删除任何旧 VHDX。

### 12.2 Desktop 隔离、配置视图与旧数据

Desktop 与 backend 进程在本轮开始及收尾均未发现；没有再次启动 Desktop。保留已安装的 Desktop，无需卸载，也没有触发卸载的数据保护前提。本轮仅修改集成设置：

| 字段 | 原值 | 本轮值 |
|---|---|---|
| AutoStart | false | false，保留 |
| IntegratedWslDistros | ["Ubuntu-26.04"] | [] |
| EnableIntegrationWithDefaultWslDistro | 原文件未显式设置 | false |
| CustomWslDistroDir 与其他配置 | 既有值 | 保留 |

字段含义参考 [Docker WSL 集成说明](https://docs.docker.com/desktop/features/wsl/) 与 [官方仓库中对应字段说明](https://github.com/docker/for-win/issues/13426)；在本机已安装 backend 二进制中也核对到同名字段。采用文本局部修改并逐项比较其余 JSON 值，没有用少量字段覆盖整份设置。

发现一个必须区别的宿主视图问题：Codex 子进程打开逻辑 %APPDATA%\Docker\settings-store.json 时，最终路径落在 Codex 包的 LocalCache\Roaming\Docker；WSL 的 /mnt/c 物理宿主视图看到另一份实际 Roaming\Docker 配置。两者内容与初始校验值不同。首次 Windows 修改只作用于缓存视图，随后已分别备份并从 WSL 修正物理宿主配置，最终两个视图都验证集成关闭。这个重定向是实测事实，尚不足以解释旧 Desktop 的 WinError 1920。

| 配置 / 备份 | SHA-256 与结果 |
|---|---|
| .wslconfig 原件备份 | b1e0dc3b048759e9e286dec61036ee4363e33b904049e6b9e2ae94aac4b2a4fd |
| .wslconfig 修改后 | 1797a0b8374eb47484188193fb9fcadfae17b2644409ebf3f015b16e50344cef |
| 实际宿主 Desktop 原件 | 0ab861eeb5034a10be6116bf775e84653e47537a42be83cb88702ef3f2983f67 |
| 实际宿主 Desktop 修改后 | fc72640febee73ddc0c7c999794741b4bfc0c47ba2d90bf1bfd4820042a96006 |
| Codex 逻辑视图首次备份 | e8d4e75562f24209f0ccf2c3a8c81fb629d0796644e90a107bc38bc9e2735e6a |
| Codex 缓存视图最终值 | 609829ed67e3ec6a8e87174a5362d29936c378b2b5bb72ff42fac16870716aab |

本地宿主配置备份及精简执行证据保存在 D:\TrustFork-Environment\native-docker-20261024-174416\，不上传。实际宿主原件为 backups\physical-settings-store.before.json；首次逻辑视图原件为 backups\settings-store.before.json；WSL 原件为 backups\wslconfig.before。不要把后续 codex-settings-store.before.json 当成首次修改前的原件。

第 11.3 节的四份旧 Desktop VHDX 均原位保留，本轮没有挂载、复制、迁移或清理它们；收尾比较的长度与 LastWriteTimeUtc 均未变。没有做这些盘的完整内容备份或哈希校验，盘内完整性与活动数据盘映射仍为 UNKNOWN，不能把“保留原文件”写成“已验证完整备份”。新原生 Engine 不复用这些 Desktop 数据盘。

### 12.3 D 盘存储链路与 swap

注册表的 Ubuntu-26.04 BasePath 位于 C:\Users\{USER}\AppData\Local\wsl\{DISTRO_ID}；fsutil reparsepoint query 证实它是 0xa0000003 目录联接，目标为 D:\WSL\{DISTRO_ID}。实际 Ubuntu 文件为该 D 盘目录中的 ext4.vhdx。Linux 根挂载为 /dev/sdd、ext4；下表的持久目录设备号均与 / 相同，且未发现将它们重定向到 DrvFS 的符号链接。

| 数据类别 | Linux 实际路径 / 依据 | Windows 后端与结论 |
|---|---|---|
| 原生 Docker 元数据、卷、容器数据 | docker info 的 DockerRootDir=/var/lib/docker；findmnt 为 /dev/sdd[/var/lib/docker]、ext4；与根目录同一设备 | D:\WSL\{DISTRO_ID}\ext4.vhdx；PASS |
| 镜像内容与容器快照 | containerd config dump 的 root=/var/lib/containerd、state=/run/containerd；数据目录 findmnt 为 /dev/sdd、ext4 | 同一 D 盘 Ubuntu VHDX；PASS。state 为 /run 内存运行态 |
| 构建缓存与 BuildKit | /var/lib/docker/buildkit 为 ext4、同一设备；Buildx default 的 driver=docker，endpoint=default，实际连接本地原生 socket | 同一 D 盘 Ubuntu VHDX；PASS；没有启动额外 BuildKit 容器或远程 builder |
| apt 包、索引和下载缓存 | /usr、/var/lib/apt、/var/cache/apt 在 Ubuntu 根文件系统；92.4 MB 包从 apt 直接下载到该发行版 | 同一 D 盘 Ubuntu VHDX；PASS；未经过 Windows Downloads |
| 本次磁盘临时目录 | 为安装进程设置 TMPDIR=/var/tmp/trustfork-native-20261024-174416，findmnt 为 /dev/sdd、ext4 | 同一 D 盘 Ubuntu VHDX；PASS |
| Linux 用户目录、Linux 配置备份 | {WSL_HOME}、/root、/var/lib/trustfork-environment/native-docker-20261024-174416 均为根 ext4 | 同一 D 盘 Ubuntu VHDX；PASS |
| /tmp | 初查为 tmpfs，未把它误称为 ext4；安装进程使用上述 /var/tmp | 内存临时数据，可交换到下述 D 盘 swap |
| 宿主配置备份、命令和测试证据 | D:\TrustFork-Environment\native-docker-20261024-174416 | D 盘普通目录，未放入 Desktop 管理目录 |
| WSL swap | /proc/swaps 为 /dev/sdc，4,194,304 KiB；不能仅凭设备名判断宿主盘 | 下述 D 盘专用后端经状态对照验证；PASS |

新安装使用 Docker 29 的 containerd image store，实测 Driver=overlayfs、DriverStatus 含 io.containerd.snapshotter.v1。分别核验两个数据根，未只看 data-root，也未将它们设置成 /mnt/d/docker。两处存储关系参考 [Docker daemon 存储说明](https://docs.docker.com/engine/daemon/) 与 [containerd image store 文档](https://docs.docker.com/engine/storage/containerd/)。

原 .wslconfig 没有显式 swapFile，原后端位置不能确认。保留实测 4 GiB 容量，向原 [wsl2] 段合并：

~~~ini
swap=4GB
swapFile=D:\\TrustFork-Environment\\swap\\native-docker-20261024-174416\\wsl-swap.vhdx
~~~

networkingMode=mirrored、autoProxy=true、dnsTunneling=true 均保留，没有更改 memory、processors 或 Windows pagefile。配置语法依据 [Microsoft .wslconfig 文档](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)。

证据链不是只看配置：新后端启动前不存在；Ubuntu 启动后在上述 D 盘物理路径生成，Linux swap 容量仍为 4 GiB；只读独占打开返回 WinError 32。受控有序停止 Ubuntu 并 wsl --shutdown 后，路径不存在（stat 返回 WinError 2）；重新启动后同一路径以新的 CreationTimeUtc 再次生成，独占只读打开又返回 32。路径的原生最终解析也确认为 D 盘。运行中的文件长度为 37,748,736 字节，不等于客体 4 GiB swap 容量。本轮未手动删除 swap 文件。

Get-DiskImage 对这个已用状态下的新 swap 仍返回 Attached=false。因此第 11.3 节历史查询的 false 只能作为该 API 的返回值，不能单独证明 WSL / HCS 没有使用对应 VHDX；它们没有提供旧 Desktop 活动映射。旧盘仍维持 UNKNOWN。

### 12.4 实际安装及客户端解耦

官方 apt 源使用 https://download.docker.com/linux/ubuntu、resolute、stable、amd64、Signed-By=/etc/apt/keyrings/docker.asc。官方 key 通过正常 TLS 获取，文件 SHA-256 为 1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570；apt 更新成功并验证签名索引。安装前先检查候选版本并 simulate，再明确选择以下版本：

| 包 | 候选及实际安装版本 | 运行时版本 |
|---|---|---|
| docker-ce | 5:29.9.2-1~ubuntu.26.04~resolute | Engine 29.9.2 |
| docker-ce-cli | 5:29.9.2-1~ubuntu.26.04~resolute | CLI 29.9.2，linux/amd64 |
| containerd.io | 2.4.2-3~ubuntu.26.04~resolute | containerd 2.4.2，runc 1.5.2 |
| docker-buildx-plugin | 0.38.1-1~ubuntu.26.04~resolute | Buildx 0.38.1 |
| docker-compose-plugin | 5.6.1-1~ubuntu.26.04~resolute | Compose 5.6.1 |

使用 apt-get --no-install-recommends；新增 13 包，0 升级、0 移除。另 8 项为 iptables、nftables、libip4tc2、libip6tc2、libnfnetlink0、libnetfilter-conntrack3、libnftnl11、libnftables1。没有删除冲突包，没有安装 Node / Pi、rootless extras 或模型插件，没有升级 Python / Harbor / Ubuntu。

当前用户新会话中 command -v docker=/usr/bin/docker，file 为 x86-64 Linux ELF；旧 Windows 转接脚本仍可能在 PATH 后部，但不再是被解析执行的命令。默认 context 的实际 endpoint=unix:///var/run/docker.sock，DOCKER_HOST / DOCKER_CONTEXT / DOCKER_CONFIG 未设置，未使用 Windows npipe。/var/run/docker.sock 权限为 root:docker、0660；未开放无认证 2375，也未 chmod 666。用户原先已属 docker 组，没有新增组授权；该组现可控制宿主级原生 daemon，具有 root 等级能力，见 [Docker 非 root 用户说明](https://docs.docker.com/engine/install/linux-postinstall/)。

用户 ~/.docker/config.json 修改前已备份。本轮只移除明确属于 Desktop 的 credsStore=desktop.exe，保留其他值；未输出或删除 auths / token。原件 SHA-256 为 13e051486615a60a7ecdba7c62a478436caa40bd924b2a118ffdf88941d3e517，修改后为 ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356。

docker.service、containerd.service 均 active / running、enabled；本发行版的实际 dockerd 进程和 /usr/bin/dockerd 已核对。收尾 docker info：CPU 20、MemTotal=16,626,081,792 字节（约 15.484 GiB）、CgroupVersion=2。这是 daemon 实测可见资源，不是给实验保证的空闲量；未额外限制整台 daemon，测试容器另设限额。服务设为 Ubuntu 启动时自动运行，不承诺 Windows 开机后 WSL 一直保持运行；WSL 空闲停止后，重新进入 Ubuntu 会启动其服务。

### 12.5 网络故障与有依据的配置变更

首次 docker pull hello-world:latest 退出 1：daemon 对官方 registry 的 HTTPS 直连连接超时。没有把它归为 Docker 安装失败，也未反复拉取。针对同一 registry 的有超时对照显示：

| 检查 | 退出码 / 观测 | 能支持的结论 |
|---|---|---|
| apt 官方源、签名索引 | 0 | apt 网络及源配置可用 |
| root shell 使用已有代理查询 registry /v2/ | curl 0，HTTP 401 | TLS 与认证入口可达；401 是匿名访问的正常认证挑战 |
| root shell 绕过代理直连同一入口 | curl 28，连接超时 | 本次直连路径不可用 |
| Docker 服务初始 Environment | 无代理字段 | shell 的代理并未自动等价为 daemon 配置 |

从本机 WSL 已有代理环境取值，并已核实它是无认证的可达回环代理，未盲抄未知 Windows 地址。在原先不存在、已记录为 ABSENT 的 /etc/docker/daemon.json 中只新增官方支持的 proxies 段，权限 0600，SHA-256 为 bc9d5b4fe9df9367d4b27be02d2ff7bcb078441d4a73181387310b110e5dc4f4。具体代理地址只保存在本机；没有关闭 TLS 校验、加入第三方镜像站或开放 daemon TCP。确认没有运行容器后重启原生服务，后续两个 pull 均为 0。方法依据 [Docker daemon 代理文档](https://docs.docker.com/engine/daemon/proxy/)。

已确认的是直连失败、代理可达、初始服务未配置代理，以及配置后拉取成功。DNS 污染、网络过滤或其他直连故障的更底层原因未定。后续拉取仍依赖该本地代理可用，不把这次成功当成无条件的网络保证。

### 12.6 逐项验收、失败记录与资源清理

本次资源前缀 tfenv-20261024-174416，统一标签 io.trustfork.environment-audit=20261024-174416。所有容器仅用于基础容器功能，不是 TrustFork 任务。常规功能命令使用 15–30 秒超时，镜像 pull 150 秒、最小 build 90 秒、服务 restart 60 秒；apt 更新 180 秒、安装 420 秒。失败后先检查原因，不采用无限重试。

| 验收项 | 状态 | 命令类别、退出码与精简证据 |
|---|---|---|
| Linux 原生客户端与真实连接 | PASS | 新用户会话解析 /usr/bin/docker；context inspect 返回本地 Unix socket；docker version 的 Client / Server 均 29.9.2，0 |
| 服务及 Desktop 解耦 | PASS | systemctl is-active / is-enabled 均 0；Desktop / backend 不在运行；本发行版实际 dockerd ELF 路径已核对 |
| D 盘持久存储和 swap | PASS | findmnt / readlink / 文件设备号 / 注册联接 / swap 状态对照，证据见 12.3 |
| 官方最小容器 | PASS | pull 后 docker run hello-world:latest，0；网络 none、CPU 0.5、内存 64 MiB、pids-limit 64；inspect State.ExitCode=0 |
| 命名卷文件读写 | PASS | writer / reader 两个 BusyBox 容器均 0；测试文件 SHA-256=68f97a5dbdec6ea52d9a39852b1d4e5856e99b4748c31bb3ad0abb001efdd57a |
| 容器本地网络 | PASS | 专用 --internal 网络的 httpd 服务与客户端 wget 请求成功，0；无宿主端口发布 |
| CPU / 内存约束 | PASS | client / server inspect 的 NanoCpus=500000000、Memory=67108864，PortBindings 为空；容器内 cpu.max=50000 100000、memory.max=67108864；0 |
| Compose | PASS | compose version、config -q、run --pull never 均 0；从已有测试卷读出原内容 |
| Buildx 本地构建 | PASS | inspect default：driver=docker，endpoint=default，BuildKit 0.34.0；用已拉取 BusyBox 作基础，仅 COPY 本地小文件，--pull=false、--network=none，无额外下载步骤；build 和新镜像运行均 0 |
| 原生服务重启持久性 | PASS | 无运行容器时 systemctl restart docker.service，0；新用户会话仍连接同一 Engine ID，原镜像 / 测试卷可读，校验值不变 |
| Ubuntu / WSL 受控重启 | PASS | 无其他发行版和无关任务时 systemctl poweroff、wsl --shutdown 均 0；启动后 boot ID 改变，Engine ID 不变，服务自动 active / enabled，已有镜像及测试卷校验仍通过 |
| 普通用户可用性 | PASS | 重启后的新 Linux 用户会话无需 sudo 即可 docker version / info / run，均 0；不是仅 root 一次性验证 |
| 现有 Harbor venv 的 Python Docker SDK ping | NOT_RUN | 独立目录及已安装分发元数据确认 Harbor 0.24.0 存在、docker SDK 分发包不存在；未为此安装新包，不能宣称 Harbor 生命周期已验收 |
| 完整实验镜像、Pi、mock、七工具、冻结恢复和真实模型 API | NOT_RUN | 本轮未执行 |

保留失败与探针限制：首次镜像 pull 的退出 1 已由有依据的代理配置解决。普通用户解析 root 进程 /proc/PID/exe 的初始断言未通过，随后以 root readlink 证实实际 /usr/bin/dockerd，普通用户探针改用可读取的 comm 与 systemd ExecStart 后继续；没有因此改 ACL。普通用户遍历 daemon 私有 BuildKit 目录也未通过，最终存储检查以 root 只读完成。停止后的 swap 状态脚本原先假设文件仍存在，stat 因 WinError 2 退出 1；未将这次探针标为成功，后续按“路径消失、重启重建”的实际状态解释。最初仅凭 import spec 判断可选 SDK 存在过于宽泛，尝试访问 DockerClient 报 AttributeError；干净工作目录和分发元数据校正后，SDK ping 保持 NOT_RUN，未调用任何模型 API。

验收完成后，核对标签、名称和停止状态，只删除本次 9 个容器、1 个专用网络、1 个测试卷、1 个构建镜像以及本次新建的三个小构建文件。清理命令均为 0，未执行全局 prune。收尾新原生引擎的 docker ps -a 与 volume ls 均为空；此结果仅针对新引擎，不代表旧 Desktop 没有容器或卷。

保留供后续复用的镜像清单：

| 镜像 | 实际 repo digest | CLI 显示大小 |
|---|---|---|
| hello-world:latest | hello-world@sha256:11a3eb1597e864c51b3f56733cb2e8a90bf0c284bfc05f9444d81c558bc848aa | 25.9 kB |
| busybox:1.37.0 | busybox@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e | 6.77 MB |

docker system df 收尾显示 2 个镜像约 6.817 MB、0 容器、0 卷；5 项本次 BuildKit 缓存约 6.795 MB 保留在 D 盘。镜像与缓存可能共享数据，不能简单相加推断物理增长。测试日志、脚本和配置备份留在 D 盘的本地证据目录，不提交到仓库。

### 12.7 配置、软件回退与磁盘变化

所有计划手动改动的既有配置先保存原件并核对 SHA-256。Linux 清单位于 /var/lib/trustfork-environment/native-docker-20261024-174416/config-manifest.json，原件在其 backups/ 子目录；清单记录 /etc/wsl.conf 与用户 Docker 配置的原属性、校验值，并记录 daemon.json、Docker apt source/key 等原先不存在。包安装前后清单也保存于该 D 盘 Ubuntu 文件系统。没有修改 shell 启动文件。

回退方案供后续需要时执行，本轮未回退：

1. 先核查无关容器 / WSL 任务；有任务则安排窗口。停止并禁用本次原生 docker.service、docker.socket、containerd.service，不删除 /var/lib/docker、/var/lib/containerd 或镜像 / 卷数据。
2. 恢复配置前先比较当前值与本报告“修改后”校验值。若用户后来已有其他改动，只合并恢复本次字段，不覆盖新修改。用户 Docker 配置从 Linux 原件恢复 uid/gid/mode；首次唯一手动移除的字段为 Desktop credsStore。将本次新建 daemon.json 移到 D 盘备份目录留存，使原先“不存在”的状态恢复，再按需 reload / restart；不批量删除目录。
3. 若需要回到原 Desktop 设置，分别恢复实际宿主 Roaming 配置与 Codex 缓存视图的原件，使用 12.2 指定的正确备份。恢复集成不等于修好 Desktop 的历史 socket 故障；不要同时启动两套 Docker。
4. 如需撤销软件，先 apt simulate 检查当前依赖，再 remove 本次新装的五个 Docker 包；不要 purge 数据或 autoremove 无关软件。其余八个新依赖只有在确认没有后续依赖后才单独处理。Docker apt source/key 原先不存在，可校验后移入 D 盘备份留存；若已被其他配置引用则先保留。
5. 若需撤销 swap 位置，备份当前 .wslconfig，按校验值恢复本次原件或只撤销新增 swap / swapFile 字段，保留其他设置；无其他任务时有序重启 WSL。D 盘现有文件由 WSL 生命周期处理，本方案不手工删除 VHDX，不调整 Windows pagefile。/etc/wsl.conf 未改，无需回退。

| 项目 | 本轮前：17:44:16 | 本轮后：18:08:19 | 边界 |
|---|---|---|---|
| C 盘可用 | 7,710,457,856 字节，7.181 GiB | 8,171,995,136 字节，7.611 GiB | 增加约 0.430 GiB；有系统 / WSL / 其他进程变化，不能全部归因于本次操作 |
| D 盘可用 | 657,118,015,488 字节，611.989 GiB | 656,881,426,432 字节，611.769 GiB | 减少约 0.220 GiB；含新引擎、索引、缓存、swap 与本地证据等同时变化 |
| Ubuntu ext4.vhdx 文件长度 | 19,918,749,696 字节 | 20,115,881,984 字节 | 文件长度增加 197,132,288 字节；不是 Linux 已用空间或宿主物理占用的直接等价值 |
| Linux 根文件系统 | — | 虚拟总容量 1,081,101,176,832 字节，可用 1,007,864,299,520 字节 | 底层仍受 D 盘实际约 611.769 GiB 余量约束，不能宣称另有约 1 TB 实盘 |

本次主动新增的大体积持久数据均定位到 D 盘 Ubuntu VHDX 或 D 盘专用目录；没有向 C 盘放置新的 Engine 包、镜像、快照、卷、构建缓存或备份。C 盘原有 Windows / WSL 组件仍会写日志、注册和少量配置，本轮修改的 .wslconfig 与 Desktop 设置也在 C 盘，不能承诺 C 盘字节数完全不变。

### 12.8 当前交接结论

原生 Docker 基础能力已 PASS，后续在 Ubuntu-26.04 使用 /usr/bin/docker 与默认 Unix socket 即可，无需 Docker Desktop 运行。Linux Python 3.12.13 / Harbor 0.24.0 仍保留。下一步可以单独准备原生 Linux Node / Pi 及必要测试依赖，再验收完整实验镜像和 Harbor / Pi 生命周期；本轮没有自动进入这些工作，也没有修改实验设计、实现代码、旧 pilot 或调用模型 API。

本次 Git 交付仅更新 docs/dynamic-join/TrustFork_Environment_Report.md，继续 research/trustfork-environment-audit 并正常推送至用户 origin，不强推。旧工作区保持原分支、ff1d6084d95b7a246c4c58f4da516c3f65a761ad 和原有六项 untracked；不以报告变更替代实验实现。

原生 Docker 安装与基础验收已完成，未修改实验代码、未调用模型 API；停止，等待后续范围安排。

## 13. Node/Pi 与离线环境联通验收（2026-10-24）

### 13.1 本轮决定、来源与操作范围

**实验不使用 Harbor。** 后续由自定义 Python 调度与消息层，通过明确的 Docker CLI / Compose 接口承担容器启动、工具执行、超时、收尾与结果收集。本轮没有实现该运行层。固定基线中的原适配器确为 class Pi(BaseInstalledAgent)，不是无 Harbor 新入口；只读核对继承关系，没有导入、运行或修改它。机器上已有 Harbor 0.24.0 原样保留，不作为本轮依赖、验收门槛或下一步待办。

执行前查询用户 origin，报告分支仍为 86d9766f87304154f2ea94f860f4cbf7a12ff67b，独立 worktree 干净；无需同步其他提交。旧 pilot 分支、HEAD 和六项 untracked 保持原样。没有创建后续实验开发分支或 PR。

干净源码由已有 Git 对象库执行 git archive 导出，唯一来源为官方固定提交 49490514f5187ba4e04b31929f2f4470e0db7def，输出到本次 Ubuntu ext4 证据目录的 source/。没有从 pilot HEAD、其工作文件或报告 HEAD 构建，也未调用 benchmark / verifier。

| 固定来源 | SHA-256 / 内容 |
|---|---|
| trustfork/base-image/Dockerfile | e92d0bd724567c84393305e2cfe48939d87b10a757ab288a6d69a32e62e65af9 |
| trustfork/tools/ensure_base_image.py | c29ab2b56464d3b5ab3eec6dc91bb8606d92d4410d89611b5951acb9c4cd12ff |
| 六项原版参数 | NODE_VERSION=24.15.0；PI_VERSION=0.84.1；PI_SUBAGENTS_VERSION=0.15.0；PI_SOURCE_COMMIT=534bcbffb7e1e7551d9ee3572dfeb278e203e493；OPENCODE_VERSION=1.18.13；OPENCLAW_VERSION=2026.7.1-2 |

基线可审核于 [原 Dockerfile](https://github.com/henrymao2004/agent-orchestration-safety/blob/49490514f5187ba4e04b31929f2f4470e0db7def/trustfork/base-image/Dockerfile) 和 [原构建脚本](https://github.com/henrymao2004/agent-orchestration-safety/blob/49490514f5187ba4e04b31929f2f4470e0db7def/trustfork/tools/ensure_base_image.py)。原共享镜像保留三 harness 的安装内容，不代表本实验要执行三个 harness；宿主未安装 OpenCode / OpenClaw，也未安装或启用 pi-subagents。

### 13.2 存储位置与现有 Docker 复核

本节约定 E={WSL_HOME}/.local/share/trustfork-env，A=E/audit-20261024-182703。{WSL_HOME} 表示当前 Ubuntu 普通用户的实际主目录；真实绝对路径已固化到本机 activate.sh 和证据清单，公开报告不包含用户名。源码、脚本、包锁及原始日志均留在 A，不上传目录内容。

| 项目 | 本地位置 | 实际存储依据 |
|---|---|---|
| Node | E/node-v24.15.0-linux-x64 | findmnt：/dev/sdd、ext4、/ |
| Pi 独立 npm 项目 | E/pi-0.84.1 | 同一根 ext4；包含 private ESM package.json、package-lock.json 和 node_modules |
| npm / uv / pip 缓存 | {WSL_HOME}/.cache/trustfork-env/{npm,uv,pip} | npm / uv 实查为同一根 ext4；pip 缓存目录仅准备，安装复用 uv |
| 下载、测试、源码与日志 | A/downloads、A/tests、A/source 及 A 内文件 | 同一根 ext4；未先下载到 Windows Downloads |
| 安装临时目录 | E/tmp | 通过 TMPDIR 显式指定在 Ubuntu 根 ext4 |
| 既有 Python venv | /mnt/d/envs/trustfork-linux | findmnt：D:\、9p / DrvFS；是既有 D 盘 NTFS 环境，本轮未迁移或偷换解释器 |
| 镜像与构建缓存 | /var/lib/docker、/var/lib/containerd、Docker 本地 BuildKit | 保持第 12 节的 D 盘 Ubuntu ext4 后端，没有改到 /mnt/d/docker |
| Ubuntu 后端 | D:\WSL\{DISTRO_ID}\ext4.vhdx | 再次检查 Windows 注册目录仍是指向此 D 盘目录的 Junction；上述 ext4 数据在该 VHDX |
| WSL swap | D:\TrustFork-Environment\swap\native-docker-20261024-174416\wsl-swap.vhdx | 保持既有 D 盘设置，收尾文件存在；未修改 4 GiB 容量 |

Ubuntu 仍为 26.04 LTS，systemd 正常；/usr/bin/docker 的 Client / Server 均为 29.9.2，默认 endpoint 为 unix:///var/run/docker.sock。Desktop / backend 本轮未运行，集成未恢复。既有 .wslconfig SHA-256 仍为 1797a0b8374eb47484188193fb9fcadfae17b2644409ebf3f015b16e50344cef；daemon.json 仍为 bc9d5b4fe9df9367d4b27be02d2ff7bcb078441d4a73181387310b110e5dc4f4。没有重装或升级 Docker、改变存储根或代理、重启无关服务、处理旧 Desktop VHDX。

### 13.3 Node / Pi 安装、依赖锁与激活

从 [Node 官方 v24.15.0 发布目录](https://nodejs.org/dist/v24.15.0/) 获取 linux-x64.tar.xz 与 SHASUMS256.txt，实际 SHA-256=472655581fb851559730c48763e0c9d3bc25975c59d518003fc0849d3e4ba0f6，与官方清单一致。使用正常 TLS；本轮未建立可信发布签名验证链，签名验证为 NOT_RUN，不能把 SHA 比对称为已验证发布签名。

安装在用户级独立目录，未覆盖系统 Node 或修改全局 shell 配置。新 shell 的 node / npm / npx 来自该目录，pi 来自该 npm 项目的 node_modules/.bin；Node 为 Linux x86-64 ELF，process.platform=linux、process.version=v24.15.0，npm=11.12.1。指定 Python 3.12.13 的 subprocess 绝对路径调用得到相同 process.execPath，没有使用 Windows Node/npm 转接脚本。

Pi 主依赖精确为 @earendil-works/pi-coding-agent@0.84.1，package.json 为 private、type=module，没有 ^ / ~ / latest、overrides 或 NODE_PATH。先取得确切 npm 元数据及 tarball，实际 tarball SHA-256=a69a18596017e91955fd0fd677be69fab5b6ea01d5b06207bcee34ee1522bc20，并校验 SHA-512 dist.integrity 与 npm pack 的 integrity 完全一致。确认发布包自带 npm-shrinkwrap.json，没有改其内部锁。

npm install --ignore-scripts 与随后 npm ci --ignore-scripts --prefer-offline 均退出 0，各安装 144 个依赖包；锁哈希前后一致，npm ls --all --json 均退出 0。没有运行额外安装脚本。实际依赖树中的 pi-agent-core、pi-ai、pi-client、pi-protocol、pi-tui 均为 0.84.1；保留完整树到 A/npm-tree.json，不能仅凭主包版本替代传递依赖证据。

| 文件（E 下） | SHA-256 |
|---|---|
| activate.sh | f0bbb743791eed704fe2f07c37ba948fa77ef6216202a71f2b2af8cf254bbdae |
| pi-0.84.1/package.json | 480d73bee4fe958eac1308b021d1495658f3805e6cb62e191721470c9c90e2eb |
| pi-0.84.1/package-lock.json | cfcf1c8bc2403c1b4291b70876ccdf122e14b42e140090d96f0b2e197f1aa35f |
| pi-0.84.1/node_modules/@earendil-works/pi-coding-agent/npm-shrinkwrap.json | a724da15dc849d0ab2fe346845f8986b059ab89339a03a365b5910b23217c0c3 |

发布包要求 Node >=22.19.0，当前版本满足；公开 ESM 入口和 CLI 与 [该版本 package.json](https://github.com/earendil-works/pi/blob/v0.84.1/packages/coding-agent/package.json) 一致。npm 元数据中的签名 / attestation 未另行验证；镜像的 PI_SOURCE_COMMIT 标签也不能据此升级为“已证明 npm 包由该 SHA 构建”。

激活方式（普通用户，显式加载，不依赖交互 profile）：

~~~bash
source "$HOME/.local/share/trustfork-env/activate.sh"
node -p 'JSON.stringify({version:process.version,platform:process.platform,execPath:process.execPath})'
command -v node npm npx pi
~~~

activate.sh 只设置实验 PATH、npm 专用配置 / 缓存、uv / pip 缓存和 TMPDIR，不给 HOME 赋值，不改全局系统设置。新建 bash --noprofile --norc 的非交互 shell 已验证；Python 使用下列明确参数方式，也已由 /mnt/d/envs/trustfork-linux/bin/python 实测：

~~~python
subprocess.run(
    [node_absolute_path, "-e",
     "console.log(JSON.stringify({version:process.version,platform:process.platform,execPath:process.execPath}))"],
    check=True, timeout=20, capture_output=True, text=True,
)
~~~

node_absolute_path 取 E/node-v24.15.0-linux-x64/bin/node，不依赖 Windows PATH。SDK 检查脚本位于 E/pi-0.84.1 内，因此公开包根 import 从同一项目解析，而不是依赖全局 pi 命令。

### 13.4 Pi 无模型验收与认证文件边界

A/empty 为新建空工作目录，A/agent 为新建独立 agentDir。root 管理入口仅用于 unshare --net 创建独立子进程网络命名空间，再以 runuser 降权到原普通用户；命名空间标识实查与宿主不同。验收环境由明确白名单构造，未继承 provider API key / token；PI_CODING_AGENT_DIR 与 session 目录明确指向 A 内，未加载旧 pilot 工作目录或用户原有 Pi 账户 / 技能 / 扩展。没有调用 prompt、continue、模型摘要、自动压缩或登录操作；安装软件源访问与这些断网功能检查分开。

| 检查项 | 状态 | 实测结果 |
|---|---|---|
| 原生 Node 身份 | PASS | Linux / v24.15.0 / 固定绝对 execPath，普通用户运行 |
| 包根 ESM 导入与公开导出 | PASS | createAgentSession、SessionManager、SettingsManager、ModelRuntime 及七个 create*ToolDefinition 均实际导出为函数 |
| 七工具定义 / schema | PASS | 实际构造 read、bash、edit、write、grep、find、ls，名称齐全，parameters 为 object schema，execute 存在；没有执行工具 |
| SDK 选项核对 | PASS | 已安装 sdk.d.ts 实查 noTools?: "all" \| "builtin"、customTools?: ToolDefinition[]；与 [固定版 SDK 源码](https://github.com/earendil-works/pi/blob/v0.84.1/packages/coding-agent/src/core/sdk.ts) 相符 |
| CLI version / help | PASS | 两项均退出 0，version=0.84.1，单项 30 秒超时，未进入交互 |
| createAgentSession 初始化、SessionManager 序列化 / 恢复 | NOT_RUN | 只验证导出和定义，本轮未创建模型会话，也未构造假成功会话对象 |
| 用户凭据隔离与无模型操作 | PASS | 白名单环境、独立 agentDir、断网命名空间；未读取 / 复制用户模型密钥，未发出模型任务 |
| 严格“任何 auth.json 都不触碰” | FAIL / 已记录限制 | CLI 自动生成并初始化了 A/agent/auth.json，2 字节、0600、内容为空对象 {}、0 个条目；不能声称全进程零 auth.json 文件访问 |

认证文件说明：该空文件属于本轮新建目录，不是用户原有账户文件；检查只确认这个本轮生成文件为空，没有查看用户其他认证文件。没有为消除此副作用修改已发布的 Pi 包，也没有以提供模型 key、伪造 auth 数据或 catch 后返回成功来掩盖。软件与离线基础调用已通过，但“完全不触碰任何 auth.json”的严格要求未达成，后续若坚持此项，需要专门处理 CLI 的初始化行为。

Node 内置测试最终收集 6 项、通过 6、失败 0、跳过 0；日志在 A/offline-host-results.json。真实 Pi 单轮调度、消息暴露、远程工具执行、冻结恢复和完整模型会话契约均不在该结果中。

### 13.5 Python 测试依赖及差异

始终使用已有 /mnt/d/envs/trustfork-linux/bin/python：Python 3.12.13，prefix 对应原 venv；fcntl 可用且是内建模块，PyYAML 6.0.3、packaging 26.3 保持。准备脚本使用系统 Python 处理文件，不将它当实验解释器。未导入 Harbor、调用其 CLI / 环境类，未安装 Docker Python SDK。

修改前 uv pip check 对 91 个现有包通过。先 dry-run 解析兼容方案，再将所有原包版本作为 constraints、四个新包固定到 A/requirements-tests.txt，重新 dry-run 后安装；安装和依赖检查均退出 0。

| 包 | 本轮前 | 本轮后 |
|---|---|---|
| pytest | 未安装 | 9.1.1 |
| pytest-asyncio | 未安装 | 1.4.0 |
| iniconfig | 未安装 | 2.3.1 |
| pluggy | 未安装 | 1.7.0 |
| 原有 91 个包 | 已有固定版本快照 | 0 变更、0 移除；包括已有 Harbor，保持原样 |

安装后为 95 包，uv pip check 通过。uv 缓存在 ext4，既有 venv 在 D 盘 DrvFS，硬链接不可用时工具自动使用完整复制；这是跨文件系统存储方式，未切换环境或重装现有软件。同步临时文件断言与 pytest-asyncio 异步队列 / 文件断言实际收集 2 项，通过 2，无跳过，最终 JUnit 在 A/python-basic.junit.xml。

### 13.6 固定原版共享镜像

起始时目标 trustfork-agents:tf-three-harnesses-v1 和原脚本 LEGACY_IMAGE 均不存在。为流式保存进度并明确来源，使用原脚本给出的相同六项参数、原始 Dockerfile 与上下文显式执行 docker build，输出独立审计标签；没有调用原脚本的“已有标签则复用”分支，没有删改 OpenCode / OpenClaw、构建简化替代镜像或修改原 Dockerfile。

| 镜像证据 | 本轮实测 |
|---|---|
| 构建标签 | trustfork-agents:original-49490514-envcheck；旧目标 / legacy 标签未覆盖 |
| 原始 FROM | python:3.12-slim，仍为原文件的可变标签 |
| 实际 base digest | python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704；pull、构建 FROM 日志及 provenance materials 一致 |
| 最终 docker image inspect .Id | sha256:9ca6c9555ff830960857b502eff60b71b669cf3f215dd4543681925bec1186a9 |
| 构建退出码 / 用时 | 0；build 约 416 秒，设置总上限 2700 秒；实际无需重试 |
| inspect Size | 2,940,919,123 字节，是镜像层统计，不直接等于新增宿主物理占用 |
| 证据 | A/image-build.log、image-build-result.json、image-build-metadata.json、image-id.txt |

daemon 继续使用此前已验证的代理拉取基础镜像。构建 RUN 另行传 Docker 支持的 HTTP_PROXY / HTTPS_PROXY / NO_PROXY 及小写 build args：现有代理仅可通过宿主回环访问，先用受控 host 网络的小容器对官方 npm registry 实测 HTTP 200，再仅为可信原版构建使用 --network=host。没有将代理写为 Dockerfile 永久 ENV、引入不明源或关闭 TLS；方法参考 [Docker proxy build args](https://docs.docker.com/build/building/variables/#proxy-arguments)。运行时验收全部使用 network none，不注入模型 key 或挂载宿主目录 / Docker socket。

主镜像 smoke 使用上述 image ID，CPU 2、内存 1 GiB、pids-limit 128，150 秒外层超时；另以同一 image ID、network none、CPU 0.5 / 内存 128 MiB 补做 Flask 实际导入，退出 0 并清理该容器。实际结果：

| 项目 | 状态 | 容器内运行或元数据证据 |
|---|---|---|
| Python | PASS | 3.12.15；与原 FROM 的 3.12 系列一致，与宿主 3.12.13 分列 |
| Node / Pi | PASS | v24.15.0 / 0.84.1；真实命令退出 0 |
| OpenCode / OpenClaw | PASS | 1.18.13 / 2026.7.1-2；只做版本查询和包元数据核对，没有模型任务 |
| bash / curl / git / jq / rg | PASS | 实际命令存在，均在 /usr/bin |
| Flask | PASS | 实际 import flask 成功，分发版本 3.1.3；补充记录为 A/image-flask-import-result.json |
| Pi 包及公开 SDK 入口 | PASS | 实际全局 npm 包为 0.84.1，入口导入及所需导出成功 |
| 原 pi-subagents | PASS | /root/.pi/agent/npm/node_modules/@tintinweb/pi-subagents/package.json，0.15.0；仅容器内原版依赖，宿主不启用 |
| /workspace 文件读写 | PASS | 新建 synthetic environment test 文件并回读正确 |
| 模型 / 任务 / 评分器 | NOT_RUN | 未调用 |

PI_SOURCE_COMMIT=534bcbffb7e1e7551d9ee3572dfeb278e203e493 仅是原构建参数和镜像标签声明；没有由它推出 npm 包构建来源已证明。原 FROM、apt 及未锁定的 Flask 等内容仍随软件源变化，本轮记录实际 digest / 版本，没有宣称整个原版镜像已达到按位可重复。

### 13.7 Python→真实 Docker CLI 验收

A/tests/test_python_docker_cli.py 使用指定 Python 3.12.13 和真实 /usr/bin/docker，通过标准库 subprocess.run 的参数数组执行，无 shell=True、mocked subprocess、Harbor 或新增容器框架。测试调用进程在独立断网命名空间中以原普通用户运行，仍通过本地 Unix socket 连接已验收 Engine；容器均 network none、CPU 1、内存 512 MiB、pids-limit 128、--pull never，不带模型凭据或宿主挂载。

| pytest 项 | 状态 | 证据 |
|---|---|---|
| 原生 CLI / Server / 精确 image ID | PASS | CLI 文件头为 ELF，Client Os=linux、Client / Server=29.9.2；default endpoint 为 Unix socket；inspect Id 与本轮记录一致 |
| 启动、exec 成功和预期失败 | PASS | 唯一标签容器实际 create / start；/workspace 写入及回读成功；故意 exit 17 被 CalledProcessError 断言识别，容器仍正常运行 |
| docker cp 文件往返 | PASS | D 盘本地临时文件→容器→本地，两次真实 cp；容器内与回传后的 SHA-256 / 字节均与原件一致 |
| 超时与容器内任务停止 | PASS | 120 秒 worker 被客户端 2 秒超时中断；确认 worker 已启动后显式 docker stop，inspect Running=false / Pid=0，再删除；没有只停 Python 客户端就宣称任务结束 |

最终收集 4 项，通过 4，错误 / 失败 / 跳过均 0，用时约 5.85 秒；Junit 为 A/python-docker.junit.xml，实际 CLI 事件为 A/python-docker-events.jsonl。事件中有一次预期 exit 17、一次预期 2 秒超时、两次 cp。finally 停止并删除本次容器，标签 io.trustfork.environment-audit=20261024-182703 收尾查询为空，没有依赖外层兜底清理来获得成功。

首轮失败如实保留：Docker 29 返回小写 error: no such object，测试最初按大写文本判断，尚未创建容器就报 1 failed / 1 passed / 2 errors；镜像 smoke 也停在同一存在性探针。已保存初始脚本及失败 JUnit / 日志到 A/backups，按实测改为大小写归一的严格“不存在”分类后再执行，最终得到上述通过结果，没有改镜像或伪造成功对象。其他准备探针修正包括 fcntl 内建模块不提供 __file__、Ubuntu 未装 rg 时改用 hashlib 做校验、隔离白名单 PATH 下使用 /usr/sbin/runuser 的绝对路径；未为修正探针安装无关软件。

### 13.8 脚本、准确调用摘录与重跑

全部脚本与完整记录在本地 D 盘，不进入报告分支；A/artifact-sha256.json 是实际绝对路径与 SHA-256 清单。下表以脱敏位置给出主要文件：

| 文件 | SHA-256 |
|---|---|
| E/pi-0.84.1/envcheck-20261024-182703.mjs | 391944a3469fe7d8bbb4ab85df9b0b0fa5d6288d9b47ea062a4510e07ea58a6f |
| A/requirements-tests.txt | 2e1e08eec44550682fe42806f6f0baa92c694ef1bfb9cec8f2e7e5f920a546dc |
| A/tests/test_python_environment.py | 3a6365970a840b84a181266f56827d1dc726a4614848a0f997ba418c1482a660 |
| A/tests/test_python_docker_cli.py | 31d9aaec5b923a5bc0ee7a730b9ce95816df78f66304a8ec25aade05fcd41915 |
| A/run-offline-host-checks.py | 121a1a8ebedadb31355aba34132c0bfe392e30aa51cef859ce62d4f4ab50864a |
| A/run-python-docker-checks.py | 9132ca07eadd61b1c8af99f27b4e16a507e6d5c47cb3bf2a43efdfc438505a82 |
| A/image-smoke.py | 40f814f3202495c7402bb72fb8ea2cf135530416e2a54b5256c49901dfe13dc4 |
| A/image-smoke-inner.py | 6c0a10e6f821156c190596fdabd1eccb11bd8ffe0ab865f32c949327efbd80e0 |
| A/check-image-flask-import.py | 71a37bab1d026ee0713b6e76893d398a26df095688e2720e9fa305b724e8a5a8 |
| A/build-original-image.py | 0a5236f01e2719b6614de28d38e39a701de19b3f4d7e77de590fdf19c6707ff7 |
| A/check-activation.py | d6d0d966f236292e0bddfa5aa5c7ea53df2fc884d818342d0964b65856fa7dc6 |

以下为已执行测试中的关键调用摘录，完整的唯一名称检查、事件记录、超时与 finally 位于对应脚本，不是另行实现的实验运行层：

~~~python
def docker(*args, check=True, timeout=25):
    p = subprocess.run(
        ["/usr/bin/docker", *args],
        check=False, timeout=timeout, capture_output=True, text=True,
    )
    if check:
        p.check_returncode()
    return p

# container 由 fixture 用已记录 IMAGE、network none 和限额创建并启动。
assert docker("exec", container, "python", "-c", code).stdout.strip() == "exec-roundtrip-ok"
with pytest.raises(subprocess.CalledProcessError) as failure:
    docker("exec", container, "sh", "-c", "printf 'expected-failure\\n' >&2; exit 17")
assert failure.value.returncode == 17

docker("cp", str(original), container + ":/workspace/inbound.txt")
docker("cp", container + ":/workspace/inbound.txt", str(copied))
assert copied.read_bytes() == payload
assert hashlib.sha256(copied.read_bytes()).hexdigest() == expected

# 超时用例明确停止整个测试容器；cleanup 在 finally 中执行。
with pytest.raises(subprocess.TimeoutExpired):
    docker("exec", name, "python", "-u", "-c", worker_code, timeout=2)
docker("stop", "--time", "3", name, timeout=20)
state = json.loads(docker("inspect", name).stdout)[0]["State"]
assert state["Running"] is False and state["Pid"] == 0
~~~

ESM 检查位于独立 Pi 项目内，实际按公开入口加载并构造七个定义，不调用 execute：

~~~javascript
const sdk = await import("@earendil-works/pi-coding-agent");
const mapping = {read:"Read", bash:"Bash", edit:"Edit", write:"Write",
                 grep:"Grep", find:"Find", ls:"Ls"};
for (const [name, part] of Object.entries(mapping)) {
  const tool = sdk["create" + part + "ToolDefinition"](isolated);
  assert.equal(tool.name, name);
  assert.equal(tool.parameters.type, "object");
  assert.equal(typeof tool.execute, "function");
}
~~~

可重跑入口（将 {WSL_HOME} 替换为本机普通用户主目录；root 入口只建立网络命名空间，脚本内实际测试降权运行）：

~~~text
wsl.exe -d Ubuntu-26.04 -u root --exec python3 {WSL_HOME}/.local/share/trustfork-env/audit-20261024-182703/run-offline-host-checks.py
wsl.exe -d Ubuntu-26.04 -u root --exec python3 {WSL_HOME}/.local/share/trustfork-env/audit-20261024-182703/run-python-docker-checks.py
~~~

原版镜像已保留，无需为重跑版本 / 联通测试再次构建。锁复装应在加载 activate.sh 后于 E/pi-0.84.1 执行 npm ci --ignore-scripts --prefer-offline；不运行模型登录或任务。集成脚本仍严格要求唯一测试名称不存在，以免覆盖别人的容器。

### 13.9 磁盘、保留项与最终交接

| 宿主可用空间 | 18:27:03 | 18:56:40 | 变化 |
|---|---|---|---|
| C | 8,134,975,488 字节，7.576 GiB | 7,942,569,984 字节，7.397 GiB | 约 -0.179 GiB |
| D | 656,940,724,224 字节，611.824 GiB | 651,247,996,928 字节，606.522 GiB | 约 -5.302 GiB |

收尾 Ubuntu ext4.vhdx 文件长度 25,743,589,376 字节，不能直接当宿主实际占用；Docker system df 显示 4 镜像约 2.95 GB、0 容器、0 卷、15 项构建缓存约 2.949 GB，镜像 / 缓存可能共享层，不简单相加。保留本轮原版镜像及 python:3.12-slim 基础镜像，也保留上轮两个小镜像；保留 Node/Pi、锁文件、源码、脚本、必要日志和缓存，不全局 prune。

本轮仅清理自身测试容器和两个 pytest 临时目录，未清理旧数据。新下载 / 安装、npm / uv 缓存、镜像、测试和日志均落在 D 盘既定位置；C 盘变化包含系统、WSL、Codex 等并行写入，不能全部归因于本次安装或承诺零变化。没有模型调用、GPU 作业、完整 benchmark、旧 pilot、verifier 或业务代码修改。

**当前分层结果：** Node/Pi 基础 SDK 与 CLI、Python 同步 / 异步测试、固定原版镜像、Python→Docker 基础容器生命周期均为 PASS，已具备开始离线代码开发的基础环境；严格零 auth.json 文件访问未达成，已记录 CLI 的空文件初始化副作用。Pi 完整调度契约、动态模块、评分、正式 case 与真实 API 仍为后续范围，Harbor 不再属于待办。本轮停在环境阶段，不自动进入这些实现或模型任务。

本次仅提交 docs/dynamic-join/TrustFork_Environment_Report.md 到原 research/trustfork-environment-audit，正常推送用户 origin，不强推、不创建 PR。
