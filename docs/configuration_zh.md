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
| `TB_DOCKER` | `PATH` 上的 `docker` | docker 可执行文件路径。 |

OpenCode 的查找顺序为显式 `HAI_OPENCODE_BIN` → 仓库内固定的 `runtime/opencode-1.18.32/bin/opencode` → PATH → `OPENCODE_PREFIX`；
显式路径不存在或版本不匹配会直接报错，不回退到另一版本。

以下历史命名变量仍被服务层使用：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HAI_NATIVE_RUNTIME_ROOT` | 根据二进制推断 | 原生求解/编辑器沙箱可只读访问的 OpenCode 运行时目录。 |
| `HAI_EXECUTION_MODEL` | 启动时指定 | 通用执行模型。 |
| `HAI_ANALYSIS_MODEL` | 启动时指定 | 通用分析/编辑模型；替代 HAI_MODEL。 |

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
| `HAI_PROVIDER_HTTP_TIMEOUT_S` | `300` | 单次上游 HTTP/socket 超时秒数；本机 fdabench 配置180。 |
| `HAI_PROVIDER_REQUEST_BUDGET_S` | `600` | 单请求重试预算秒数；本机配置420。流式读取也检查预算，整个 Agent 另有总超时。 |
| `HAI_PROVIDER_SLOT_TIMEOUT_S` | `120` | 等待全局模型请求并发槽的超时秒数。 |
| `HAI_FDABENCH_TIMEOUT_S` | `600` | 原生 FDABench 单 trial 总超时，本机配置900；业务 HTTP/Python 使用其接入配置的 timeout。 |
| `HAI_INTELLIGENT_TIMEOUT_S` | 未额外限制 | OpenCode 分析/编辑等智能会话的额外总超时上限，本机配置1200。 |
| `HAI_PROVIDER_SLOT_DIR` | `/tmp/harnesslens-provider-slots` | 跨进程并发槽的锁目录。 |
| `HAI_PROVIDER_TRIAL_SLOT_DIR` | `/tmp/harnesslens-provider-trial-slots` | 同上，trial 维度。 |
| `HAI_OPENCODE_TURN_RETRY_ATTEMPTS` | `0` | opencode 单轮重试次数。 |
| `HAI_MIN_MEM_GB` | `0`（不检查） | rollout 前要求的最小空闲内存 GB。 |
| `HAI_MIN_FREE_GB` | `0`（不检查） | rollout 前要求的最小空闲磁盘 GB。轨迹与工作区很占盘，长跑建议设。 |

## FDABench 与运行环境

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HAI_FDABENCH_ROOT` | `<repo>/third_party/fdabench-lite-report` | FDABench 数据集根目录。 |
| `HAI_FDABENCH_INDEX` | `<repo>/runs/fdabench-assets/documents.sqlite` | FDABench 文档检索索引。 |
| `HAI_FDABENCH_ARTIFACTS` | `<repo>/runs/fdabench` | FDABench 产物输出目录。 |
| `HAI_FDABENCH_MAX_CONCURRENCY` | `8` | FDABench 并发上限，允许 1–64。 |
| `HAI_FDABENCH_WEB_SEARCH` | `disabled` | FDABench 工具检索模式，仅允许 `disabled` 或 `live`。 |
| `ZHIPU_API_KEY` | — | FDABench 文档检索服务 API key。 |
| `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` | — | 从 HuggingFace 下载 FDABench 数据集所需凭据。 |
| `HAI_NATIVE_EXECUTION_ATTEMPTS` | `2` | 原生执行的基础设施失败重试次数，允许 1–3。 |
| `HAI_DOCKER_HOST` / `DOCKER_HOST` | rootless 推导 | 显式指定 docker daemon 端点，优先于 rootless 推导。 |
| `HAI_DOCKER_ROOT` | 模板推导 | rootless docker 的状态目录。 |
| `HTTP_PROXY`（或小写 `http_proxy`） | — | clash 代理读取的宿主代理地址。 |

## 迭代协议

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HAI_CONFIRMATION_MODE` | `always` | `always` = 晋升前必须过 confirm 复验；`off` = 跳过。设成 `off` 跑出来的结果只能当探索性证据。 |
| `HAI_BASELINE_REUSE_POLICY` | — | 控制 baseline event 的复用严格程度。 |
| `HAI_KEEP_TRAJECTORY_WORKSPACE` | `0` | 设为 `1` 保留每个 trial 的工作区（很占盘，调试用）。 |

---

## 框架自动设置的变量（不要手动配）

下面这些由底层适配从 `DEEPSEEK_*` 推导后写入子进程环境。
手动设置它们不会生效，只会造成困惑：

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
.venv/bin/python scripts/check_env.py --cell fdabench --harness opencode
```

它会真的去解析 `benchmark_config()`，所以报出来的是所选 cell **实际**需要的
文件、虚拟环境和可执行文件，而不是一份猜测清单。缺任何一项都会以非 0 退出。

## 历史变量与内部桥接

`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_URL` 仅供旧底层适配兼容；新任务必须明确选择两组连接。`HAI_MODEL_CONNECTIONS` 是启动器传给任务的无密钥连接记录，`HAI_PROXY_API` 是记录代理使用的协议选择，`HAI_PROXY_MODEL` 是旧协议转换代理使用的上游模型；这两个由系统生成，无需手工设置。
