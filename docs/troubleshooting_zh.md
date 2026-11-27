# 常见问题

先跑体检，它能覆盖大部分环境类问题：

```bash
.venv/bin/python scripts/check_env.py --cell <cell> --harness <harness>
```

---

## 启动阶段

### `workflow source changed during the run; start a new run ID`

run 进行中源码变了。控制器在每个阶段边界都会校验
`runs/train/<run-id>/workflow_fingerprint.json`，这是为了保证一次 run 的所有产物
出自同一份代码。

**处理**：换一个 `--run-id` 重新开始。不要为了"续上"而把代码改回去——只要有一个
字节不同，指纹就对不上。

### `existing run has no workflow fingerprint and cannot be safely resumed`

run 目录里已经有阶段产物，却没有指纹文件（通常是从更老的版本迁移过来的目录）。

**处理**：换新 run-id。

### `baseline event runtime fingerprint differs from this run`

`--baseline-event` 指向的基线是用不同的 rollout 运行时代码跑出来的。参与指纹的
文件列表见 `harnesslens/evolution/baseline.py` 的 `BASELINE_RUNTIME_FILES` 与
`BenchmarkConfig.runtime_files()`。

**处理**：重跑基线，或者换一个匹配的 baseline event。**其他源码树产出的 baseline
event 在这里一律不可用**——路径常量变了，指纹必然不同。

### `argument --cell: unknown benchmark cell '<name>'`

cell 名不在别名表里。报错会直接列出合法值：

```
error: argument --cell: unknown benchmark cell 'fdabnch';
expected one of: fdabench | /path/to/benchmark.toml
```

每个 cell 都有多个别名（`fdabench-lite-report` 等），完整表在
`harnesslens/benchmarks/cell_config.py` 的 `_ALIASES`。这是 argparse 阶段的校验，
不会等到 run 开始才失败。

---

## 环境与依赖

### `opencode executable is unavailable`

查找顺序：`PATH` → `HAI_OPENCODE_BIN` → `<OPENCODE_PREFIX>/bin/opencode`
（`OPENCODE_PREFIX` 默认 `~/.opencode`）。

**处理**：装 opencode，或把 `OPENCODE_PREFIX` / `HAI_OPENCODE_BIN` 指对。

### `bubblewrap is required for isolated Harness Editor calls`

Harness Editor 在隔离沙箱里改文件，需要 `bwrap`。

**处理**：`apt install bubblewrap`（或发行版对应包）。

---

## 迭代过程

### `Analyzer portfolio has no unattempted candidate`

组合里的候选都试过了。这是**正常收尾**，不是错误：本轮证据已经榨干。

**处理**：想继续就跑新一轮，用新的 baseline 或新的 rollout 证据喂进去。

### `an iteration requires at least five tasks` / `a paired screen requires at least two tasks`

预算已经不够支撑一次合格的配对评测
（`MIN_STANDARD_ROLLOUT_TASKS = 5`，`MIN_RESIDUAL_ROLLOUT_TASKS = 2`）。

**处理**：提高 `HAI_TOTAL_CREATION_BUDGET`，或者接受这次 run 就此收尾。刻意
把任务数压到下限以下是不允许的——那样的对比不足以支撑结论。

### `a residual probe is not promotion eligible`

`residual_probe` 模式跑出来的候选按设计就不能晋升，它只是探针。

**处理**：预算够的时候用 `standard` 模式复跑该候选。

### `candidate acceptance requires attributable positive evidence`

分数涨了，但涨幅归因不到被改的那个通道上。这是有意的拦截：防止把噪声当成改进。

**处理**：看 `runs/train/<run-id>/main_agent/` 下的 review 产物，确认候选的行为假设
是否真的被触发了。

### Channel preflight 失败

改动落地了，但运行时没加载它——改了 skill 而 skill 工具没启用、改了 config 而被
固定覆盖顶掉，都属于这类。

**处理**：读 `runs/train/<run-id>/main_agent/*-channel-preflight.json`。它会指出
具体哪个通道没生效。通常意味着 Harness Query 把某个通道误判为可改，值得回头看
那份报告。

### `no complete OpenCode trace`

某个 trial 的轨迹缺少完整的 API sidecar。缺 trace 的 rollout 不可用于归因，因此
直接拒收。

**处理**：重跑该 trial。反复出现的话，检查 provider 代理层的日志与
`HAI_PROVIDER_RETRY_ATTEMPTS`。

---

## 资源

### 磁盘被 rollout 工作区占满

**处理**：确认 `HAI_KEEP_TRAJECTORY_WORKSPACE` 没设成 `1`；把
`HAI_*_RUNTIME_CWD_ROOT` 指到大盘；`runs/` 本身也可以软链出去。

### provider 限流

**处理**：调低 `HAI_MAX_ROLLOUT_CONCURRENCY` 与
`HAI_PROVIDER_MAX_CONCURRENCY`。所有 cell 共用同一个 `DEEPSEEK_API_KEY`，
所以并行跑多个实验时限流是叠加的——要么错开跑，要么把并发降下来。

### 进程被杀后预算账本对不上

**处理**：直接用同一个 run-id 重新执行。控制器启动时会调用
`recover_interrupted_jobs()` 回收未结算的会话，并写出
`controller_recovery.json`。

---

## 测试

### `test_query_receives_bounded_documentation_content[pi-...]` 被 skip

pi 运行时没装。pi 的文档在 npm 包里，不随本仓库分发。

### `test_repository_is_self_contained` 失败

有模块引用了未声明的本地项目，或引用了本仓库之外的目录。这个测试用于守住"自包含"
这条线：把需要的数据 vendored 进 `assets/`，或者把路径改成走环境变量。

### `test_no_source_file_hardcodes_a_developer_absolute_path` 失败

有人写死了 `/home/...`、`/root/...`、`/data1/...` 这类路径。

**处理**：改成环境变量 + `expanduser()` 的默认值，参考
`harnesslens/infrastructure/rootless_docker.py` 里 `HAI_DOCKER_ROOT` 的写法。
