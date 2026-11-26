# 实验启动配置

每次实验选择一份 TOML 配置和一个实验编号。界面与命令行服务入口使用同一份配置。

| 配置 | 用途 | 默认 |
| --- | --- | --- |
| `benchmark` | 内置题库名称，或外部 `benchmark.toml` 路径 | 本轮用 `crm` |
| `initial_harness` | 初始 OpenCode Harness 目录，或已导出的完整 Harness JSON 包 | **省略或空字符串表示空 v0** |
| `agent_config` | HTTP/Python 调用、答案和 trace 映射配置 | 省略则使用本机原生 OpenCode |
| `env_file` | 私有模型地址、凭据、外部数据位置等 | 模板使用仓库 `.env` |
| `[models.execution]` / `[models.analysis]` | **必填**，各自选择模型、协议、地址、密钥环境变量名 | 不再默认共用；见 [模型连接](model-connections.zh-CN.md) |
| `mode` | train、test_baseline 或 test_candidate | train |
| `full_evaluation` | TRAIN 后冻结并评测 TEST | 界面默认开启；直接使用 TOML 时需显式 true |
| `[environment]` | 会话预算和并发等实验设置 | 预算200；并发由模板和界面选择 |
| `[components]` | 优化组件的实验边界；模型在范围内自行发现和选择 | 默认16类全允许，denied为空 |

模型凭据只写私有 `.env`。远程业务 Agent 的固定运行时和模型由业务服务配置；平台模型用于分析、编辑和选优。

配置文件中的相对路径均相对于该 TOML 所在目录。例：保存为 `configs/experiments/crm.local.toml`：

```toml
schema = "harnesslens.experiment.v1"
benchmark = "crm"
mode = "train"
full_evaluation = true
initial_harness = ""  # 默认空；也可填 ../../harnesses/business-agent
agent_config = "../../examples/agents/company-http.local.toml"
env_file = "../../.env"
readiness = "draft"   # 完成接口/trace/数据冒烟后改 ready

[environment]
HAI_TOTAL_CREATION_BUDGET = 200
HAI_MAX_ROLLOUT_CONCURRENCY = 1
HAI_MAX_ANALYSIS_CONCURRENCY = 1
HAI_PROVIDER_MAX_CONCURRENCY = 1

[models.execution]
managed_by = "business_agent"

[models.analysis]
model = "david/gpt-6.2-sol"
api = "responses"
base_url = "https://api.david-ai.net/v1"
api_key_env = "HAI_ANALYSIS_API_KEY"

[components]
allowed = ["*"]
denied = []
# 如需固定权限/MCP：denied = ["permissions", "mcp_servers"]
```

会话预算不是费用或 token 上限。一次 train 实验内部可能有多轮优化。CRM 的训练为 query1–10，query11–13 为最终独立评测用工程留出，不在训练中优化。

`allowed` 是候选上限，不会强迫模型选择全部组件。先读取实际Agent能力和基线工具目录，再由模型发现可改项，候选通过真实生效检查后才进入评测。业务接入还受服务能力声明约束；详见 [16组件协议](OPENCODE-COMPONENTS.zh-CN.md)。

## 初版目录与空初版

普通目录按 OpenCode project 目录导入，保留文件名与相对路径：

```text
harnesses/business-agent/
  AGENTS.md
  .opencode/skills/<name>/SKILL.md
  .opencode/agents/<name>.md
  ...引用的脚本与资料
```

需要 home/project 两种发现位置时，可用 `home/`、`project/` 两个子目录，根目录不混放其他文件。输入目录只放 Harness 文件，不放整个业务代码仓库、`.env`、安装依赖或符号链接；支持 UTF-8 文本和脚本，沿用每文件2MiB、总16MiB限制。

不指定初版时，平台冻结空快照为 v0，表示不额外提供自定义 Harness；业务固定工具、运行时和服务端固定配置仍由实际执行环境决定。指定初版不会自动开放其全部能力：实际加载受业务接入声明和运行时支持约束，不支持的配置会被拒绝。不要把模型/provider凭据或不受当前加载器支持的完整生产配置放进初版。

## 保存、继承、回退与恢复

输出统一在 `runs/train/<run_id>/`，不需要分别设置候选、trace、评分和回退目录：

- `initial_harness.json`：初版来源、摘要及冻结快照位置。
- `rollout_evidence/<run_id>/versions_percell/<benchmark>/v0/`：冻结初版；候选位于同级独立目录，并记录父版本。
- `baseline/`、`rollout*/`、分析目录：轨迹、评分和阶段记录。
- `submission/final.json`：选定版本、快照及完整 Harness 包引用。

输入目录不被修改。候选从当前采用版本继承；候选未被采用时保留父版本。最终即使选择非空 v0，也导出其真实文件，并在 TEST 中加载这些文件。

同一实验恢复使用已冻结快照；直接 CLI 恢复时可以省略初版参数。再次指定不同初版会拒绝混用，要求新 run_id。平台配置还会检查输入指纹，源目录发生变化后应新建实验。不同初版不能共用旧基线评分缓存。

下一次实验可将之前 `final.json` 中 `harness_package.path` 指向的完整包作为 initial_harness；final.json 本身只是结果索引，不是完整输入包。

## 启动

界面：在 Experiment console 点击 New experiment，在 Configure your run 中选择配置模板、执行/分析模型、16组件开放范围和进化参数，点击 Start run 即创建并排队；也可用 Save draft 仅保存。左侧切换真实实验，Overview 保持左谱系、右曲线；Configuration 查看冻结配置，Artifacts 查看原始日志/trace/答案，Activity 查看队列和检查点事件。已移除示例选择、播放和回放进度条。每个任务保存独立配置，不改模板；API 与 Worker 需事先运行。本机可用 `.venv/bin/python scripts/start_local_platform.py` 启动平台，打开 http://127.0.0.1:3210/experiments。密钥仅留服务端。

无需 Web/API 时，同样可用本地队列入口执行配置：

```bash
.venv/bin/python -m harnesslens.service create crm-001 --profile configs/experiments/crm.local.toml
.venv/bin/python -m harnesslens.service start crm-001
.venv/bin/python -m harnesslens.service worker --once
```

直接运行算法也支持可选参数（预算等环境变量需在进程启动前设置）：

```bash
.venv/bin/python run_e2e.py --cell crm --harness opencode --run-id crm-001 --models-config configs/experiments/crm-local.toml
# 有初版时增加 --initial-harness /absolute/path/to/harness
# 接业务服务时增加 --agent-config /absolute/path/to/agent.toml
```

独立评测初版：`run_test_baseline.py --initial-harness ...`；不提供时评测空初版。评测最终版本：`run_test_candidate.py --patch-json .../submission/final.json`，加载所选快照，无需再指定初版。

部署和 Linux/HTTP 测试数据的边界见 [INTRANET.zh-CN.md](INTRANET.zh-CN.md)。本机已有完整实验记录，可从实验管理页查看 TRAIN/TEST、候选采用结果和原始证据；查看不会重新运行。

## 界面中的 Benchmark 和 Harness 目录

当前界面从项目根目录自动发现，不再要求用户手填服务器路径：

- `benchmarks/<id>/benchmark.toml`：注册入口；自有 JSONL 数据固定为 `data/tasks.jsonl`，可选 `scorer.py` 和 `references/`。目录名和 manifest 的 `id` 一致。已有原生适配器也有注册入口，原数据路径保持兼容。
- `harnesses/<name>/project/`：放业务初始 `AGENTS.md`、`.opencode/skills/` 等；可选并列 `home/`。也可放导出的 `package.json`。不选时使用 Empty Harness。
- 启动后自动生成 `harnesses/<run-id>/library.json` 和 `versions/<version>/harness-<sha256>.json`。初始和候选分别保留；最终采用的版本标记 Selected，可直接作为下一轮实验的初始 Harness。业务原目录不会被覆盖。

训练／测试数量直接在 Benchmark 下方设置，最大值来自它自己的固定划分。提供 `domain_field` 的数据才出现 domain 选择；未提供时全部数据视为一个 domain。FDABench 使用其公开的数据库分组。这里的 TEST 是最终保留集，不会作为训练验证题混入进化。每轮内部验证仍沿用原算法。

开启完整评测后，实际顺序是：选定 TRAIN 全量 baseline → 多轮 TRAIN 子集修改、配对验证与必要的确认 → 冻结最终版本 → 初版 TEST baseline → 最终版本 TEST。初版 TEST 当前在训练结束后补测，不参与优化决策；若最终仍选择初版，就复用它的 TEST 成绩。Evaluation 只显示这两份 TEST 成绩，中间候选轮次放在 Lineage，不作为 TEST 曲线点。一次实验没有额外的“每个候选都跑 TEST”的外层循环。

添加目录后重新打开 New experiment 即可刷新列表。详细文件规范见 [`benchmarks/README.md`](../benchmarks/README.md) 和 [`harnesses/README.md`](../harnesses/README.md)。数据、业务 Harness 和自动生成的版本均默认不上传 GitHub；服务器上自行复制或下载数据后即可使用。
