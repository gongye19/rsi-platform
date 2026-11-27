# RSI Platform

基于 [HarnessLens](https://github.com/jhxu5214/HarnessLens) 扩展的 Agent 自进化实验平台，支持配置 Benchmark、独立的执行／分析模型和组件权限，并在实验台查看组件谱系与评测曲线。

[公网演示](https://rsi-platform-demo.vercel.app/experiments) · [English](README.md) · [内网部署](docs/INTRANET.zh-CN.md)

公网演示使用浏览器本地的模拟数据，不连接业务 Agent 或模型 API。真实实验通过本地 API 和 Worker 执行，支持 Python 函数和 HTTP 接入业务 Agent。

任务启动需分别指定执行与分析模型，详见 [模型连接配置](docs/model-connections.zh-CN.md)。

## 上游 HarnessLens

**Verify Smarter, Evolve Further：通过行为感知验证实现高效 Harness 演化**

本项目在上游论文的 OpenCode、Codex CLI 和 Pi Coding Agent 实现上扩展，包括完整的 TRAIN
演化流程与独立的 blind TEST 评测入口。保留原有 MIT 许可证和作者署名；内部 Python 包继续使用 `harnesslens` 名称。

[English](README.md)

实验参数统一见 [启动配置](docs/STARTUP.zh-CN.md)：初始 Harness 可选，不指定即为空 v0。

**内网 Linux（无 Docker）部署**：从 [内网使用指南](docs/INTRANET.zh-CN.md) 开始。
Python 依赖由 uv/uv.lock 管理；API、独立 Worker、实验管理界面与离线依赖准备脚本已提供。

新增题库可使用 [通用 benchmark 适配](docs/BENCHMARK-ADAPTERS.zh-CN.md)，复用 Python／HTTP 调用、trace 和原有选优流程。

已有业务 agent 也可通过 [Python 函数或 HTTP API 接入](docs/BUSINESS-AGENTS.zh-CN.md)，用配置映射其现有参数和返回字段。

## 目录结构

```text
harnesslens/
  core/               配置、预算、持久化与共享协议
  evolution/          Controller 及诊断/演化阶段
  harnesses/          可编辑面、manifest 与 agent runtime adapter
  benchmarks/         benchmark 任务驱动、MCP server 与评分逻辑
  evaluation/         rollout service 与 blind TEST 评测
  infrastructure/     进程、代理、provider 与容器工具
run_*.py              完整回路及 blind TEST 的公开入口
configs/              benchmark runtime 配置
assets/               vendored harness 文档
scripts/              安装、环境体检、单阶段工具和维护脚本
tests/                离线测试及 3 组 live runtime 测试
runs/                 run 产物（已 gitignore）
```

## 依赖

| | |
| --- | --- |
| Python | 3.11+ |
| Python 包 | `pyyaml`、`httpx`、`loguru` 和 `pytest` |
| Provider | OpenAI-compatible chat-completions endpoint |
| Agent runtime | **opencode**、**codex**、**pi** 至少一个 |
| Benchmark | 本地准备好的 FDABench 数据（`scripts/prepare_fdabench.py`）或自定义 JSONL benchmark |

论文实验的 target-agent 和 evolution roles 均使用 `deepseek-v4-flash-preview`，harness
版本分别为 OpenCode v1.17.13、Codex CLI v0.144.4 和 Pi Coding Agent v0.80.10。
Benchmark 数据和 agent runtime 体积较大且许可独立，因此不随仓库分发；复现文档固定了
所需版本和配置。

## 安装

```bash
git clone https://github.com/gongye19/rsi-platform.git
cd rsi-platform

# 创建 .venv、安装 HarnessLens 依赖，并生成 .env。
scripts/setup.sh

# 配置 provider。
$EDITOR .env  # 执行/分析密钥；任务 TOML 分别指定两组模型
```

## 环境准备

Agent runtime 是外部依赖，解析方式见 [docs/benchmarks_zh.md](docs/benchmarks_zh.md)。
FDABench 数据在服务器上用 `scripts/prepare_fdabench.py` 本地准备。机器相关的路径、
Docker 和代理设置见 [docs/configuration_zh.md](docs/configuration_zh.md)。

## 快速开始

```bash
.venv/bin/python scripts/check_env.py --cell fdabench --harness opencode
scripts/run_e2e.sh --run-id fdabench-001 --cell fdabench --harness opencode
```

通过 `--cell` 和 `--harness` 选择其他支持的环境或 harness。中断后用相同 `--run-id`
重新执行即可恢复。产物位于 `runs/train/<run-id>/`；最终 harness 是
`submission/final.json`，`controller_state.json` 记录 checkpoint。

### Blind TEST 评测

Blind TEST 与演化流程刻意分离。TRAIN Controller 产出 `submission/final.json` 后才能运行：

```bash
.venv/bin/python run_test_candidate.py --benchmark fdabench --harness opencode \
  --run-id fdabench-001-test \
  --patch-json runs/train/fdabench-001/submission/final.json
```

`run_test_baseline.py` 使用相同 blind protocol 评测对应的未修改 harness。

## 测试

```bash
scripts/run_tests.sh
```

传入 `--live` 可额外运行真实 runtime 和 provider 检查。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/architecture_zh.md](docs/architecture_zh.md) | 模块、验证协议和产物布局 |
| [docs/configuration_zh.md](docs/configuration_zh.md) | 环境变量及 runtime 行为 |
| [docs/benchmarks_zh.md](docs/benchmarks_zh.md) | benchmark 数据准备和 cell 配置 |
| [docs/troubleshooting_zh.md](docs/troubleshooting_zh.md) | 常见错误及诊断方法 |

## 适用范围与局限

论文实验覆盖一个模型家族和三种 harness。Interaction unit 使预算
可审计，但没有对不同角色和环境的 token、延迟或货币成本做归一化。行为感知演化在多个
任务暴露同一种可控行为时最有效；面对目标和执行路径高度多样的任务集，孤立修复可能缺少
可迁移证据，此时正确结果可能是不修改 incumbent。

## 许可证

HarnessLens 使用 [MIT License](LICENSE)。`assets/` 下 vendored 的文档沿用上游条款；
OpenCode插件/工具的离线JavaScript依赖包保留各包许可证，来源与固定版本见 `configs/opencode-plugin-runtime.json`。
benchmark 数据和OpenCode主程序不随Git仓库分发。

## FDABench-Lite 报告实验

已加入 105 道可评分报告题（70 TRAIN / 35 TEST）、16 个只读数据库和完整 PDF 检索工具。服务器下载数据、预检和启动命令见 [FDABench 指南](docs/FDABENCH.zh-CN.md)。
