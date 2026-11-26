# Linux 内网交付与使用

每次实验的最终配置清单见 [STARTUP.zh-CN.md](STARTUP.zh-CN.md)。`initial_harness` 可选，不指定就是空 v0；指定后冻结为该实验的初版快照。

部署方式为普通 Linux 用户下的 **uv + systemd API + 单 Worker + Next.js 界面**，不需要 Docker。CLI 仍然可独立使用。API 只调度任务，Worker 以子进程执行原来的训练/评测入口；没有重写优化算法。

## 交付内容和依赖

- Python 用 `pyproject.toml`、`uv.lock` 管理。交付脚本使用 Python 3.13；项目兼容 Python ≥3.11，但离线 wheels 固定为 3.13。
- OpenCode 固定 1.18.32，单独安装在本项目 `runtime/`，不覆盖系统或业务实例的 OpenCode。Linux x64/ARM64 官方归档 SHA256 见 `configs/opencode-assets.json`。
- 优化器的 Harness Editor 需要 bubblewrap 和可用的 Linux namespace。管理员可安装 `bubblewrap`；若内核或公司策略禁用 namespace，环境检查失败即停止，需要管理员提供等价隔离，不能直接关闭沙箱。
- 界面使用 Node ≥22、Bun 1.3.12 和 `web/bun.lock`，不由 uv 管理。仅用 CLI/API 时不需要前端依赖。
- CRM 需要专用测试 PostgreSQL（推荐与原快照相同的 17 系列）和 13 题外部数据。代码仓库不包含数据库、题目答案、凭据和历史实验。

Linux 必须允许 bubblewrap 创建所需的命名空间；公司策略若禁用该能力，需管理员配置后再运行优化器。预检失败会阻止启动，不提供关闭隔离的绕过选项。

## 安装

在 Linux 有公司 Python/npm 镜像源或允许访问依赖源时：

```bash
git clone https://github.com/gongye19/rsi-platform.git
cd rsi-platform
bash scripts/setup_linux.sh
# 填写本机 .env，权限保留 600；不要从个人电脑复制生产凭据。
cd web
bun install --frozen-lockfile
bun run build
cd ..
```

完全离线时，先在可联网电脑准备对应架构的依赖；准备脚本需要 uv、Python 和 pip：

```bash
python3 scripts/prepare_offline.py --arch x86_64
# ARM64 使用 --arch aarch64
```

将整个 `offline/linux-x86_64/`（或 aarch64）带入内网。内网需预先有 uv、Python 3.13、bubblewrap；执行：

```bash
bash scripts/setup_linux.sh --offline /path/to/offline/linux-x86_64
```

`SHA256SUMS.json` 记录离线包各文件摘要，OpenCode 安装时再次验证固定 SHA256。安装依赖使用 `--no-index --require-hashes`，不访问公网。离线包不包含 uv/Python/系统包/Node/Bun，需通过公司软件源提前安装。

前端完全离线交付需在**相同 Linux 架构和兼容 glibc 的联网预备机**完成 `bun install --frozen-lockfile && bun run build`，再携带 `web/node_modules/` 和 `web/.next/`；不要复制 macOS 的 node_modules/.next 到 Linux。也可在公司 npm 镜像上重新构建。源代码中无外部字体/CDN运行依赖。

更大的 FDABench 报告实验及服务器数据下载命令见 [FDABench 指南](FDABENCH.zh-CN.md)。

## 准备 13 题

外网本机已有数据时，`python scripts/export_crm_data.py` 会生成私有 `offline/crm-data.tar.gz` 和校验文件。这些不会进入 GitHub。

```bash
mkdir -p third_party
tar -xzf /path/to/crm-data.tar.gz -C third_party
```

默认从 `third_party/dataagentbench/` 读取，也可在 `.env` 设置 `HAI_DAB_ROOT=/absolute/dataagentbench`。对外提供的业务测试环境也必须有相同数据指纹；宿主评分器和验证答案只放平台端。

公司管理员在专用测试 PostgreSQL 的 loopback 55432 端口准备空实例后，可使用导入脚本。它只创建固定的新测试库/只读角色，发现已存在则拒绝修改；不要指向生产实例。管理员连接串放私有 `.env` 的 `CRM_BENCHMARK_ADMIN_DSN`，不要放终端命令或 Git。

```bash
.venv/bin/python scripts/init_crm_postgres.py --create-isolated-benchmark-db
```

为 `h2_crm_reader` 只配置本机 loopback 到 `h2_crm_support_v1` 的访问。当前 SQL 代理适用测试实例本机只读角色免密认证；不会把管理员连接或凭据传给 Agent。管理员角色不能对 Agent 网络开放。导入标记和六表内容要通过 `scripts/check_intranet.py --crm` 的规范指纹检查。

## 接业务 Agent

1. 复制 `examples/agents/company-http.toml` 到 `examples/agents/company-http.local.toml`，填写现有 HTTP/trace 接口地址、字段映射、版本和鉴权环境变量。令牌写 `.env`。
2. 在业务端评测入口为每个请求创建独立 session，按请求加载候选文件，返回版本/摘要回执。实际模型请求和工具轨迹可由主接口返回，或由单独 trace 接口按 request/session 获取。
3. 将隔离 CRM 数据/工具接到该评测 session，确认业务端能查询。平台本机 `source/query.py`、文件路径和 localhost 代理不能被另一台机器直接使用。可以准备同指纹测试副本或接公司已有只读工具网关；**本仓库没有自动在业务机器安装远程数据网关**。
4. 复制 `configs/experiments/crm-company.toml` 为 `crm-company.local.toml`，让 agent_config 指向私有配置；确认冒烟通过后才把 `readiness` 改成 `ready`。模板默认 draft，不能误启动付费实验。

Python 适配是 Worker 本地 Python 函数调用；业务包和其依赖必须可访问，可在 `agent.python` 指定业务独立解释器。通用 JSONL benchmark 可使用 Linux Python 适配。**当前 CRM 的本机原生执行/SQL沙箱仍是 macOS Seatbelt；Linux Python CRM 路径会拒绝缺少端口隔离的执行。Linux 上本轮采用远程 HTTP 业务接入。** `scripts/run_crm.py` 的本机原生沙箱探针不可作为 Linux HTTP 冒烟命令。

HTTP/trace字段、回执协议与通用接收端见 [BUSINESS-AGENTS.zh-CN.md](BUSINESS-AGENTS.zh-CN.md)。16组件的交付与本机执行机制已接通；profile默认全纳入探索，也可通过 `[components]` 缩小范围。实际业务接口能力声明与实验许可取交集，模型依运行时证据选择，再做候选preflight；原5项proposal_only继续保留。声明全部能力不能代替接入真实业务加载器。

## 启动平台

在 `.env` 增加 `HAI_SERVICE_TOKEN`（至少24字符随机串），仅供平台 API 与 Next.js 服务端使用，不会进入浏览器。可以用 Python 的 `secrets.token_urlsafe(32)` 在本机生成后手动写入 `.env`；不要提交。

```bash
.venv/bin/python scripts/check_intranet.py --crm --profile configs/experiments/crm-company.local.toml
.venv/bin/python -m harnesslens.service plan --profile configs/experiments/crm-company.local.toml
.venv/bin/python scripts/install_services.py --web --enable
systemctl --user status harnesslens-api harnesslens-worker harnesslens-web
```

安装脚本生成当前用户 systemd units，不改系统服务，不自动创建/启动实验。API 默认 `127.0.0.1:8765`，界面 `127.0.0.1:3000`。`.env` 的键值用 systemd EnvironmentFile 兼容的 `KEY=value` 格式（不要写 `export`、命令替换或多行值）。需要后台跨退出运行时由管理员为该用户启用 linger。没有用户 systemd 的机器，可由公司进程管理器运行下面两个命令；先安全导入私有环境变量：

```bash
.venv/bin/python -m harnesslens.service api
.venv/bin/python -m harnesslens.service worker
```

界面使用 SSH 隧道访问，例如 `ssh -L 3000:127.0.0.1:3000 user@platform-host`，打开 `http://127.0.0.1:3000/experiments`。浏览器端没有独立登录；对多人开放时必须由公司反向代理提供 TLS/SSO/访问控制，API 仍留 loopback。API token 不等于浏览器用户权限。

从界面选择 `.local.toml` 模板，再选择执行/分析模型、16组件开放范围、预算、TRAIN/TEST重复次数和并发；更多设置可调整超时、重试、初始Harness与experimental字段。原5类proposal_only保持只读。业务HTTP/Python执行模型由业务服务管理，界面不会覆盖其模型。

点击 Start run 将创建并启动；Save draft 只保存草稿。两者都先将本次配置冻结到 `runs/service/profiles/{id}/profile.toml`，不修改模板。Save draft 不调用模型；Start run 随后排队，由 Worker 调用真实模型。草稿可之后在控制台点击 Start run；Resume run 恢复、Stop run 请求停止。启动/恢复会消耗模型配额。默认执行TRAIN→冻结v0与最终版本→TEST；如果最终仍是v0，只评一次TEST并复用该结果。可取消训练后TEST。会话预算沿用原算法的TRAIN创建计数，TEST与其他已有独立预算不计入其中，并非总费用上限。可查看谱系、状态/预算、事件和产物。正式控制台只展示真实实验记录，不提供示例回放。日志/trace可能含业务内容，按公司数据权限保存。

## CLI、API 与恢复

```bash
.venv/bin/python -m harnesslens.service create crm-001 --profile configs/experiments/crm-company.local.toml
.venv/bin/python -m harnesslens.service start crm-001
.venv/bin/python -m harnesslens.service status crm-001
.venv/bin/python -m harnesslens.service stop crm-001
.venv/bin/python -m harnesslens.service resume crm-001
```

API 使用 `Authorization: Bearer $HAI_SERVICE_TOKEN`：

| 方法/路径 | 用途 |
| --- | --- |
| GET /health | 不带鉴权的存活检查 |
| GET /v1/profiles | 管理员配置目录内可选 TOML |
| GET /v1/options | 服务端模型目录、16组件与参数边界；不返回密钥 |
| POST /v1/runs | `{profile, run_id?, settings?: {models, components, parameters, initial_harness, full_evaluation}}` 创建草稿 |
| GET /v1/runs、/v1/runs/{id} | 列表、状态和预算/检查点 |
| POST /v1/runs/{id}/start、stop、resume | 操作任务 |
| GET /v1/runs/{id}/events?after=序号 | 增量事件，最多500条；支持 SSE 格式的有限批次，客户端重连携带游标 |
| GET /v1/runs/{id}/history | 真实产物转换的16组件谱系 |
| GET /v1/runs/{id}/artifacts | 产物目录（最多2500条；完整文件在平台本地） |
| GET /v1/runs/{id}/artifact?root=0&path=... | 受目录约束的文本读取，单文件最多16MiB |

SQLite 队列和事件在 `runs/service/`；训练在 `runs/train/{id}/`，测试在 `runs/test_baselines/{id}/`、`runs/test_candidates/{id}/`；都写平台端。当前只有**同一主机一个 Worker**，不是多机调度系统。

停止只操作本平台拥有且启动标识匹配的子进程组；systemd 同时收拢本服务 cgroup。停止不会自动取消已提交的远端 HTTP 工作。Worker 异常重启把旧 running 任务标为 interrupted，不自动重新消耗配额。恢复复用原算法已有检查点/完整缓存；若业务调用中断且结果不明，会保留现场拒绝静默重试，需要先按 request_id 查远端状态，然后决定新建实验。改变配置/代码/数据指纹后应新建 run_id。

最终候选为 `runs/train/{id}/submission/final.json` 及其中的不可变 Harness 包，默认只作为实验输出，不自动发布到线上。保持 query1–10 TRAIN、query11–13 工程留出；留出3题此前已在工程中出现，不宣称全新盲测。

接其他 benchmark 时添加外部 `benchmark.toml` 并把实验 profile 的 benchmark 指向该文件；详见 [BENCHMARK-ADAPTERS.zh-CN.md](BENCHMARK-ADAPTERS.zh-CN.md)，不需要为每个数据集改优化器。

## 本机快速打开界面

已有 uv 环境、Node 与前端构建后，可以运行：

```bash
.venv/bin/python scripts/start_local_platform.py
# http://127.0.0.1:3210/experiments
.venv/bin/python scripts/start_local_platform.py --stop
```

启动API、Worker、Next生产服务，不启动实验。不占用其他项目已使用的端口；可用 `--web-port` / `--api-port` 调整。私有令牌自动写入被git忽略的 `.env`、`web/.env.local`，模型密钥仅留在后端。已有CLI完成/失败实验只读登记，其原始产物与重复次数不变。端口、进程记录和日志在 `runs/platform/`；内网长期运行仍使用前述systemd方式。
