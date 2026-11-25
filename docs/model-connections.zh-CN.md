# 执行模型与分析模型

每次启动必须明确选择两组连接；可以相同，也可以完全不同，不会默认共用一组。

- **执行**：运行 benchmark 中的问题，生成业务答案。
- **分析**：Discovery、Experience、Analyzer、Main Agent、Harness Editor，负责诊断、生成和修改候选。

本机当前选择执行 `crm/glm-5.2`、分析 David AI 的 `david/gpt-6.2-sol`。`david`、`crm` 是本地 provider 标签；实际上游模型名是斜线后的部分。David 的模型名来自该平台目录，不代表其他平台也提供同名模型。

CRM 13 题的得分仍由官方 Python validator 计算，不调用分析模型充当评分器。这里的分析连接不是额外的 LLM judge；开放问答 benchmark 的评分器由其适配配置决定。

## 启动任务时指定

复制一份 `configs/experiments/crm-local.toml` 为 `crm.local.toml`，设置下面两张表，再在界面或 CLI 选择这份配置：

```toml
[models.execution]
model = "crm/glm-5.2"
api = "chat_completions"
base_url_env = "HAI_EXECUTION_BASE_URL"
api_key_env = "HAI_EXECUTION_API_KEY"

[models.analysis]
model = "david/gpt-6.2-sol"
api = "responses"
base_url = "https://api.david-ai.net/v1"
api_key_env = "HAI_ANALYSIS_API_KEY"
```

`model`、`api`、`api_key_env` 必填；`base_url` 或 `base_url_env` 必须选一个。模型格式为 `provider/model`。`api` 支持 `chat_completions` 和 `responses`；当前 OpenCode 1.18.32 的分析端和原生执行端均支持这两种协议。旧 benchmark 的模拟用户仍沿用其现有 Chat Completions 接口要求。

私有 `.env` 只放地址和密钥，不提交 Git：

```dotenv
HAI_EXECUTION_BASE_URL=https://your-execution-provider.example/v1
HAI_EXECUTION_API_KEY=your-execution-key
HAI_ANALYSIS_API_KEY=your-analysis-key
```

两边可以引用同一个 key 环境变量，但必须在配置中显式写出。密钥值不得写入 TOML 或命令行；记录中只保存变量名。不要将 `.env` 放入初始 Harness 目录。

```bash
# 非付费预检；显示实际选择的两组连接，不请求模型
.venv/bin/python scripts/run_crm_experiment.py --profile configs/experiments/crm.local.toml --run-id experiment-001
# 确认连接恢复后，沿用同一配置进行 smoke → TRAIN → 冻结 TEST
.venv/bin/python scripts/run_crm_experiment.py --profile configs/experiments/crm.local.toml --run-id experiment-001 --run
```

界面先选择启动配置，显示两组模型，再创建并启动任务。缺少任一模型组、地址、协议或对应凭据，启动会被拒绝；不会先花费执行基线再发现分析配置缺失。配置或引用的地址改变后必须新建实验编号；单独轮换密钥不改变实验指纹。Worker 的 `experiment.json` 与本机启动器的 `configuration.json` 保存不含密钥的实际连接记录；直接 CLI 在对应 run 目录的 `model_connections.json` 冻结同样的记录。

直接调用原算法入口时，可指定同样包含这两张表的 TOML：

```bash
.venv/bin/python run_e2e.py --cell crm --harness opencode --run-id direct-001 --models-config configs/experiments/crm-local.toml
```

`--models-config` 只读取两张模型表；其他 benchmark、初始 Harness 和业务适配参数仍使用该 CLI 原有参数。也可明确设置两组 `HAI_EXECUTION_{MODEL,BASE_URL,API,API_KEY}` / `HAI_ANALYSIS_{MODEL,BASE_URL,API,API_KEY}` 环境变量。服务启动会将所选 TOML 解析成这些通用变量。

`HAI_CRM_MODEL` 已改名为 `HAI_EXECUTION_MODEL`，`HAI_MODEL` 改为 `HAI_ANALYSIS_MODEL`。旧名仅作为底层历史适配的兼容读取，不再满足新任务启动的必填要求。历史 `DEEPSEEK_*` 只在旧适配内部桥接；分析端使用自己选定的连接，不从执行端补密钥或地址。

## HTTP / Python 业务 Agent

业务服务自己管理执行模型，平台不能通过改一个模型字段改变远程模型。此时显式配置：

```toml
[models.execution]
managed_by = "business_agent"

[models.analysis]
model = "david/gpt-6.2-sol"
api = "responses"
base_url = "https://api.david-ai.net/v1"
api_key_env = "HAI_ANALYSIS_API_KEY"
```

同时指定已有的 `agent_config`。平台只调用业务接口和获取 trace；分析调用和记录保留在平台端。没有 `agent_config` 时不能选择 `business_agent`。

## Trace 与验证

分析和原生执行分别启动本机记录代理，代理只持有对应角色的上游凭据；OpenCode 子进程只获得本机代理占位 token。Chat Completions 保持原协议转发；Responses 保持原生 `input`、`instructions`、reasoning、tool item 和最终 response，不转换成 Chat 格式。两者继续保留完整 API 请求、响应和 token 用量。Responses 不注入不受支持的 `seed`，模型随机性由 provider 决定；任务配对及接受规则不变。

2026-11-25：David 模型目录可访问，`gpt-6.2-sol` Responses 实际请求通过；OpenCode 1.18.32 隔离分析调用和用量记录通过。这是连接验证，不是 13 题完整自进化实验。
