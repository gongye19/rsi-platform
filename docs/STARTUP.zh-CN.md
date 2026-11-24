# 实验启动配置

每次实验选择一份 TOML 配置和一个实验编号。界面与命令行服务入口使用同一份配置。

| 配置 | 用途 | 默认 |
| --- | --- | --- |
| `benchmark` | 内置题库名称，或外部 `benchmark.toml` 路径 | 本轮用 `crm` |
| `initial_harness` | 初始 OpenCode Harness 目录，或已导出的完整 Harness JSON 包 | **省略或空字符串表示空 v0** |
| `agent_config` | HTTP/Python 调用、答案和 trace 映射配置 | 省略则使用本机原生 OpenCode |
| `env_file` | 私有模型地址、模型名、凭据、外部数据位置等 | 模板使用仓库 `.env` |
| `mode` | train、test_baseline 或 test_candidate | train |
| `[environment]` | 会话预算和并发等实验设置 | 模板预算200、并发1 |

模型凭据只写私有 `.env`。远程业务 Agent 的固定运行时和模型由业务服务配置；平台模型用于分析、编辑和选优。

配置文件中的相对路径均相对于该 TOML 所在目录。例：保存为 `configs/experiments/crm.local.toml`：

```toml
schema = "harnesslens.experiment.v1"
benchmark = "crm"
mode = "train"
initial_harness = ""  # 默认空；也可填 ../../harnesses/business-agent
agent_config = "../../examples/agents/company-http.local.toml"
env_file = "../../.env"
readiness = "draft"   # 完成接口/trace/数据冒烟后改 ready

[environment]
HAI_TOTAL_CREATION_BUDGET = 200
HAI_MAX_ROLLOUT_CONCURRENCY = 1
HAI_MAX_ANALYSIS_CONCURRENCY = 1
HAI_PROVIDER_MAX_CONCURRENCY = 1
```

会话预算不是费用或 token 上限。一次 train 实验内部可能有多轮优化。CRM 的训练为 query1–10，query11–13 为最终独立评测用工程留出，不在训练中优化。

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

界面：在实验管理页选择配置，创建后启动；API 与 Worker 需事先运行。

无需 Web/API 时，同样可用本地队列入口执行配置：

```bash
.venv/bin/python -m harnesslens.service create crm-001 --profile configs/experiments/crm.local.toml
.venv/bin/python -m harnesslens.service start crm-001
.venv/bin/python -m harnesslens.service worker --once
```

直接运行算法也支持可选参数（预算等环境变量需在进程启动前设置）：

```bash
.venv/bin/python run_e2e.py --cell crm --harness opencode --run-id crm-001
# 有初版时增加 --initial-harness /absolute/path/to/harness
# 接业务服务时增加 --agent-config /absolute/path/to/agent.toml
```

独立评测初版：`run_test_baseline.py --initial-harness ...`；不提供时评测空初版。评测最终版本：`run_test_candidate.py --patch-json .../submission/final.json`，加载所选快照，无需再指定初版。

部署和 Linux/HTTP 测试数据的边界见 [INTRANET.zh-CN.md](INTRANET.zh-CN.md)。本机真实模型实验仍待 API 恢复后启动。
