# 配置参考

## 配置来源与优先级

```
已 export 的 shell 环境变量        ← 最高优先级
        ↑
<repo>/.env.local                  （gitignore，放机器特有的覆盖）
        ↑
<repo>/.env                        （gitignore，放主配置）
        ↑
代码内默认值                        ← 最低优先级
```

由 `harnesslens/core/config.py:load_repo_env()` 实现，用的是 `os.environ.setdefault`，
所以**已经存在的环境变量永远不会被 .env 覆盖**。每个入口脚本在解析完参数后立刻
调用它。

从 `.env.example` 复制一份开始：

```bash
cp .env.example .env
```

---

## 必填

| 变量 | 说明 |
| --- | --- |
| `HAI_EXECUTION_API_KEY` | 执行连接的凭据；远程业务执行由业务服务管理时不需要。 |
| `HAI_EXECUTION_BASE_URL` | 执行连接地址；由任务的 models.execution.base_url_env 引用。 |
| `HAI_ANALYSIS_API_KEY` | 分析连接的独立凭据。 |

每次任务须在 TOML 中明确配置 `[models.execution]` 与 `[models.analysis]`，分别选择模型、协议、地址和凭据变量名。详见 [模型连接](model-connections.zh-CN.md)。服务启动时以所选 TOML 为准，私有 env_file 提供引用值；直接 CLI 支持 `--models-config` 或两组显式的通用环境变量。

---

## 路径

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HARNESSLENS_ROOT` | 包所在目录的上一级 | 仓库根。只有把包装到仓库外时才需要设置。 |
| `HAI_REPO_ROOT` | 同上 | MCP server 子进程用的仓库根，由父进程自动注入。 |
| `HAI_BENCHMARK_CONFIG` | — | 外部 benchmark TOML 的绝对路径。传入 `--cell /path/benchmark.toml` 时自动设置，供子进程和恢复解析相同 benchmark ID。 |
| `HAI_SERVICE_TOKEN` | — | 内网平台 API 的随机 Bearer token，至少24字符；只放私有环境文件，由 API 与 Next.js 服务端使用，禁止 NEXT_PUBLIC 前缀。服务部署见 INTRANET.zh-CN.md。 |
| `OPENCODE_PREFIX` | `~/.opencode` | opencode 安装前缀；实际用的是 `<prefix>/bin/opencode`。 |
| `HAI_OPENCODE_BIN` | — | 直接指定 opencode 可执行文件，优先级高于 PATH 和 `OPENCODE_PREFIX`。 |
| `HAI_OPENCODE_VERSION` | — | 指定时启动前严格校验版本；本机固定 `1.18.32`。 |
| `HAI_OPENCODE_LEGACY_CLI` | `0` | 设为 `1` 时不传 `--auto`，仅兼容旧版 CLI。1.18.32 使用 `0`。 |
| `PI_AGENT_BIN` / `PI_BIN` | `<repo>/.pi-agent/node_modules/.bin/pi` | pi 可执行文件。 |
| `HAI_CODEX_MODELS_CACHE` | `~/.codex/models_cache.json` | codex 模型目录缓存，会被复制进每个隔离的 `CODEX_HOME`。 |
| `HAI_TERMINAL_BENCH_CACHE` | 工作区内 `.cache/terminal_bench/shared_trials` | terminal-bench 共享 trial 缓存。 |
| `TAU2_DATA_DIR` | `third_party/tau3-bench/data` | tau2 数据目录。checkout 不在约定位置时用它指过去。 |
| `TB_DOCKER` | `PATH` 上的 `docker` | docker 可执行文件路径。 |

OpenCode 的查找顺序为显式 `HAI_OPENCODE_BIN` → 仓库内固定的 `runtime/opencode-1.18.32/bin/opencode` → PATH → `OPENCODE_PREFIX`；
显式路径不存在或版本不匹配会直接报错，不回退到另一版本。

CRM 扩展配置见 [CRM 接入](CRM.zh-CN.md)，主要变量如下：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HAI_DAB_ROOT` | `third_party/dataagentbench` | CRMarenapro 原始任务、数据与官方 grader 所在 checkout。 |
| `HAI_CRM_RUNTIME_ROOT` | 根据二进制推断 | 原生求解/编辑器沙箱可只读访问的 OpenCode 运行时目录。 |
| `HAI_CRM_POSTGRES_PORT` | `55432` | 宿主 PostgreSQL 端口；原生 agent 经临时受限代理访问。 |
| `HAI_EXECUTION_MODEL` | 启动时指定 | 通用执行模型；替代 HAI_CRM_MODEL。 |
| `HAI_ANALYSIS_MODEL` | 启动时指定 | 通用分析/编辑模型；替代 HAI_MODEL。本机使用 David AI gpt-6.2-sol。 |

---

## 预算与并发

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HAI_TOTAL_CREATION_BUDGET` | `200` | 一次 run 允许创建的隔离智能会话总数（硬上限）。 |
| `HAI_TRAIN_ROLLOUT_REPEATS` | `2` | 每个 TRAIN 任务的 trial 数，只允许 `1` 或 `2`。论文实验用 2。 |
| `HAI_MAX_ROLLOUT_CONCURRENCY` | `20` | rollout 并发，允许 1–30。 |
| `HAI_MAX_ANALYSIS_CONCURRENCY` | `20` | 分析类角色的并发。 |
| `HAI_PROVIDER_MAX_CONCURRENCY` | `20` | provider 代理层的全局并发闸。 |
| `HAI_PROVIDER_TRIAL_MAX_CONCURRENCY` | `20` | 单个 trial 维度的 provider 并发闸。 |
| `HAI_PROVIDER_RETRY_ATTEMPTS` | `4` | provider 单请求总尝试次数（含首次，最多6次）；仅重试临时限流、5xx及连接异常，明确额度不足/鉴权错误立即停止。 |
| `HAI_PROVIDER_HTTP_TIMEOUT_S` | `300` | 单次上游 HTTP/socket 超时秒数；本机 CRM 配置180。 |
| `HAI_PROVIDER_REQUEST_BUDGET_S` | `600` | 单请求重试预算秒数；本机配置420。流式读取也检查预算，整个 Agent 另有总超时。 |
| `HAI_PROVIDER_SLOT_TIMEOUT_S` | `120` | 等待全局模型请求并发槽的超时秒数。 |
| `HAI_CRM_MAX_CONCURRENCY` | `2` | CRM 任务并发上限，本机配置4；仍受 rollout/global provider 上限约束。 |
| `HAI_CRM_TIMEOUT_S` | `600` | 原生 CRM 单 trial 总超时，本机配置900；业务 HTTP/Python 使用其接入配置的 timeout。 |
| `HAI_INTELLIGENT_TIMEOUT_S` | 未额外限制 | OpenCode 分析/编辑等智能会话的额外总超时上限，本机配置1200。 |
| `HAI_PROVIDER_SLOT_DIR` | `/tmp/harnesslens-provider-slots` | 跨进程并发槽的锁目录。 |
| `HAI_PROVIDER_TRIAL_SLOT_DIR` | `/tmp/harnesslens-provider-trial-slots` | 同上，trial 维度。 |
| `HAI_OPENCODE_TURN_RETRY_ATTEMPTS` | `0` | opencode 单轮重试次数。 |
| `HAI_MIN_MEM_GB` | `0`（不检查） | rollout 前要求的最小空闲内存 GB。 |
| `HAI_MIN_FREE_GB` | `0`（不检查） | rollout 前要求的最小空闲磁盘 GB。轨迹与工作区很占盘，长跑建议设。 |

## 迭代协议

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HAI_CONFIRMATION_MODE` | `always` | `always` = 晋升前必须过 confirm 复验；`off` = 跳过。设成 `off` 跑出来的结果只能当探索性证据。 |
| `HAI_BASELINE_REUSE_POLICY` | — | 控制 baseline event 的复用严格程度。 |
| `HAI_TAU2_TIMEOUT_PER_TURN_S` | 见 `rollout_bridge.py` | tau2 单轮超时。 |
| `HAI_KEEP_TRAJECTORY_WORKSPACE` | `0` | 设为 `1` 保留每个 trial 的工作区（很占盘，调试用）。 |

---

## 分 cell 的变量

### tau2（retail / banking）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HAI_TAU2_RETRIEVAL_CONFIG` | `bm25` | banking_knowledge 的检索配置，不能为空。 |
| `TAU2_MAX_TOOL_RESULT` | `0`（不截断） | 工具结果的最大字符数。 |
| `HAI_TAU2_LLM_MODEL` | — | 覆盖 tau2 用户模拟器所用模型。 |
| `HAI_TAU2_MCP_DEBUG_LOG` | — | tau2 MCP bridge 的调试日志路径。 |

### Terminal-Bench

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HAI_DOCKER_ROOT` | `~/dockers` | rootless dockerd 的状态目录，**其余全部由它推导**。状态目录在别的盘上时必须设，否则守护进程会用一个空目录，表现为"镜像和容器全没了"。 |
| `HAI_DOCKER_HOST` | 由 `HAI_DOCKER_ROOT` 推导 | docker socket。显式设置时会校验它确实位于状态目录内，不一致直接报错。 |
| `DOCKER_HOST` | — | 标准 docker 变量，优先级最高。 |
| `TB_IMAGE_TEMPLATE` | 见 `terminal_images.py` | 任务镜像命名模板。 |
| `TB_NO_REBUILD` | — | 设为 `1` 时禁止重建镜像（要求已预拉取）。 |
| `TB_SHARED_NETWORK` | `harnesslens-terminal-bench` | 容器共享网络名。 |
| `TB_ENABLE_CONTAINER_CLASH` | 空 | 是否在容器内启用 clash 代理。 |
| `TB_CLASHCTL_HOME` | `~/clashctl` | clash 控制器目录（内含 `bin/mihomo`）。 |
| `TB_CONTAINER_PROXY_URL` / `TB_CONTAINER_HTTP_PROXY` / `TB_CONTAINER_HTTPS_PROXY` | — | 容器内代理地址。 |
| `TB_MODEL_ENDPOINT_NO_PROXY` | `1` | 让 provider 端点绕开代理。 |
| `TB_CLASH_START_CONCURRENCY` | `2` | clash 启动并发。 |
| `TB_OPENCODE_VERSION` | `latest` | 注入容器的 opencode 版本。 |
| `TB_SKIP_OPENCODE_INSTALL` | 空 | 跳过容器内 opencode 安装。 |
| `TB_OPENCODE_MODEL` | `deepseek/deepseek-v4-flash` | 容器内 opencode 使用的模型。 |
| `TB_CLASH_DNS_URL` | 空 | clash 的 DNS 上游地址。 |
| `TB_DOCKER_HOST_PROXY_HOST` | 自动探测 | 容器访问宿主代理时使用的地址。 |

`.venv/bin/python scripts/check_env.py --cell terminal-bench` 会打印它实际要连的 socket
及其来源（`DOCKER_HOST` 还是默认值），socket 不存在时报 MISS。


---

## 框架自动设置的变量（不要手动配）

下面这些由 `tau2_driver._configure_tau2_deepseek_env()` 从 `DEEPSEEK_*` 推导后写入
子进程环境，供 tau2 内部的 litellm 使用。手动设置它们不会生效，只会造成困惑：

| 变量 | 来源 |
| --- | --- |
| `OPENAI_API_KEY` | `DEEPSEEK_API_KEY` |
| `OPENAI_BASE_URL` / `OPENAI_API_BASE` | `config.provider_base_url()` 的解析结果 |
| `HAI_REPO_ROOT` | 父进程的仓库根，注入给 MCP server 子进程 |

要改端点或密钥，改 `DEEPSEEK_BASE_URL` / `DEEPSEEK_API_KEY`。

---

## 运行时工作区根目录

下面这几个变量指定各 harness 在 rollout 时的 cwd 根。默认在 run 产物树内，
只有当那块盘太小或不是本地盘时才需要改：

`HAI_OPENCODE_RUNTIME_ROOT`、`HAI_CODEX_RUNTIME_CWD_ROOT`、
`HAI_PI_RUNTIME_CWD_ROOT`

---

## 验证配置

```bash
.venv/bin/python scripts/check_env.py --cell retail --harness opencode
```

它会真的去解析 `benchmark_config()`，所以报出来的是所选 cell **实际**需要的
文件、虚拟环境和可执行文件，而不是一份猜测清单。缺任何一项都会以非 0 退出。

## 历史变量与内部桥接

`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_URL` 仅供旧底层适配兼容；新任务必须明确选择两组连接。`HAI_MODEL_CONNECTIONS` 是启动器传给任务的无密钥连接记录，`HAI_PROXY_API` 是记录代理使用的协议选择，`HAI_PROXY_MODEL` 是旧协议转换代理使用的上游模型；这两个由系统生成，无需手工设置。
