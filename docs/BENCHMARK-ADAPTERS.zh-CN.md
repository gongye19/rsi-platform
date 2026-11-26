# 通用 benchmark 接入

优化器保留 HarnessLens 的探索、诊断、候选、配对比较、确认与晋升流程。新增 benchmark 不需要在优化器中添加题库判断。
OpenCode 组件目录、业务调用、trace、加载预检、版本交付也不随题库重做。

| 层 | 实现 | 职责 |
| --- | --- | --- |
| 优化器 | `harnesslens/evolution/` | 行为诊断、修改假设、候选比较与选优 |
| Agent 执行 | `harnesslens/harnesses/business_agent.py` | Python/HTTP 调用、字段映射、认证、独立 trace |
| 执行生命周期 | `harnesslens/evaluation/business_runtime.py` | Harness 文件交付、配对 seed、超时、评分调用、缓存与证据校验 |
| Benchmark 适配 | `harnesslens/benchmarks/adapters.py` | 公开输入、环境准备、资源生命周期、宿主评分、拆分和指纹 |

CRM 的数据库、只读代理、官方评分器保留在 CRM 适配层。JSONL 是另一种 benchmark，复用同一业务执行生命周期。
原有 tau2、BIRD、Terminal-Bench 的原生执行路径继续保留；交互式任务不能直接当成单轮问答包装。

## 接入 JSONL 问答 benchmark

目录可以放在仓库外，不必修改优化器源码：

```text
my-benchmark/
  benchmark.toml
  tasks.jsonl
  grader.py          # 可选，自定义宿主评分器
```

配置示例：

```toml
schema = "harnesslens.business-benchmark.v1"
id = "my_qa"
tasks = "tasks.jsonl"
train = ["q1", "q2"]
test = ["q3"]
id_field = "id"
prompt_field = "question"
public_fields = ["question", "context"]
reference_field = "answer"
grader = "exact"
max_concurrency = 2
```

任务示例：`{"id":"q1","question":"...","context":"公开资料","answer":"宿主参考答案"}`。
任务ID使用字母、数字、下划线、连字符和点，不能包含路径分隔符。训练与测试拆分必须非空、唯一、互不重叠。
`public_fields` 是明确的公开输入清单，不能包含 `reference_field`。
业务端只收到公开字段；原始任务文件、参考答案和 grader 不会交付到任务工作区。
默认评分为答案去除首尾空白后与参考答案精确比较，适合验证接入；正式业务可使用官方评分器适配。

使用现有业务 Agent 配置：

```bash
.venv/bin/python scripts/check_env.py \
  --cell /absolute/path/my-benchmark/benchmark.toml \
  --agent-config /absolute/path/agent.toml --harness opencode

scripts/run_e2e.sh --run-id my-qa-001 \
  --cell /absolute/path/my-benchmark/benchmark.toml \
  --agent-config /absolute/path/agent.toml --harness opencode
```

预检不调用模型，训练会实际调用配置的业务服务和优化模型。
`--cell` 接受描述文件路径并解析为稳定的 benchmark ID。
`HAI_BENCHMARK_CONFIG` 自动记录其绝对路径，子进程或恢复通过它解析同一 ID；
恢复时推荐继续传入相同描述文件，配置、数据、grader 或业务源码改变会拒绝复用旧结果。

测试仍走原入口：

```bash
.venv/bin/python run_test_baseline.py --run-id my-qa-test \
  --benchmark /absolute/path/my-benchmark/benchmark.toml \
  --agent-config /absolute/path/agent.toml --dry-run

.venv/bin/python run_test_candidate.py --run-id my-qa-test \
  --benchmark /absolute/path/my-benchmark/benchmark.toml \
  --agent-config /absolute/path/agent.toml \
  --patch-json runs/train/my-qa-001/submission/final.json --dry-run
```

去掉 `--dry-run` 后才执行真实 TEST 调用。示例数据见 `examples/benchmarks/arithmetic/`，仅用于接入演示。

## 自定义宿主评分

```toml
grader = "python"
grader_file = "grader.py"
grader_function = "grade"
grader_timeout = 60
```

`grader.py` 提供 `grade(task, answer)`，返回0/1、布尔值，或 `{"reward": 0或1}`。
它在宿主侧独立进程接收完整原始 task，可调用已安装的官方 validator；不随请求发送给业务 Agent。
这是你明确配置的可信代码。其文件哈希进入实验指纹，评分异常或超时会作为工程故障停止，不冒充正常零分。
返回奖励用于现有 pass@1/pass@2 协议，满分1表示通过。

## 特殊环境与更多 benchmark

JSONL 入口适用于已有 Python/HTTP Agent 的单轮问答任务。数据库、交互模拟器、容器或附件准备等特殊环境，
在 benchmark 适配层实现 `BenchmarkAdapter`：

- `split()`：明确 TRAIN/TEST；
- `explorer_input()` / `public_task()`：只提供公开信息；
- `prepare_task()` / `execution_context()`：准备 source 和受限资源；
- `grade()`：宿主评分；
- `fingerprint()`：数据、运行配置与评分器身份；
- `loading_contract()`：提供真实加载器和工具事实，不预设模型的编辑结论。

继承 `BusinessBenchmark` 即可复用 Python/HTTP 执行、配对、恢复和 trace 校验，再在 benchmark 注册处接入。
原生运行器可实现 `run_batch()`，CRM 就采用这种方式。新增运行环境仍需要开发和验证对应适配器，
不能声称任意 benchmark 只改一个路径就能运行。

## 验证范围

新增 JSONL benchmark 已用本地模拟模型验证 Python 与 HTTP 两种调用：TRAIN、候选指令生效预检、TEST、
独立命令行基线/候选入口、跨进程配置解析、缓存零新增请求和指纹变化拒绝复用。
它不启动 CRM 服务，也不向业务输入暴露参考答案或 grader。
CRM 原生 OpenCode、Python、HTTP 路径另做回归。以上工程验证不代表真实解题收益，也没有启动付费进化实验。

## 连续评分

返回 `[0,1]` 部分分的 Python grader 可在 benchmark TOML 中设置 `primary_metric = "mean_reward"`，以配对试验的平均 reward 为优化目标。默认仍为 `pass_at_1`；连续评分不改变通用的归因、确认和回退条件。FDABench 内置适配器使用同一套机制。

## 可配置数据子集与 domain

实验 profile 的 `[dataset]` 可设置 `domain`、`train_count`、`test_count`，独立于运行模型、组件权限和每题重复次数。所有适配器的数量选择都保持原 TRAIN／TEST 边界，并冻结具体任务 ID。

JSONL 描述文件若要提供 domain 筛选，可增加 `domain_field = "domain"`，同时把 `domain` 放进 `public_fields`。每条题目应包含非空 domain 字符串。domain 不能指向参考答案字段，也不能来自私有评分信息。没有 domain 元数据的 benchmark 按整个 benchmark 作为一个任务组；框架不会凭空推断行业分类。
