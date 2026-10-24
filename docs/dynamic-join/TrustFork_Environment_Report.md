# TrustFork 动态入队研究：环境检查报告

检查日期：2026-10-24，Asia/Shanghai（UTC+8）。宿主资源主快照：16:24:28。Docker 启动续查：同日 16:54–17:09；原始资源快照和续查结果分别注明。资源值随运行状态变化。

**最新续查结论：已按用户授权启动安装好的 Docker Desktop，但后台在初始化本地 sailor-ingest.sock 时以 WinError 1920 失败，Linux daemon 仍不可达；实际 WSL 集成可用性未通过，daemon CPU / 内存、当前数据 VHDX 映射和镜像清单均为 UNKNOWN。配置路径与历史文件大小不能替代运行证据。详见第 11 节。本次仍未进入 Part2。**

本报告依据 Part1 新版要求和用户随后明确允许“启动现有 Ubuntu，只读检查”的补充授权。PASS 表示该项实查成功；FAIL 表示当前明确缺失或不满足该项；UNKNOWN 表示证据不足；NOT_RUN 表示未执行。版本查询成功不代表集成验收通过。

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

环境检查已完成，未开始安装环境或修改实验代码；等待你核对报告后再继续。
