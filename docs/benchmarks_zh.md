# 基准数据准备

平台内置原生 FDABench benchmark，并支持配置驱动的自定义 JSONL benchmark。FDABench
数据在服务器上用 `scripts/prepare_fdabench.py` 本地准备，详见
[FDABench 指南](FDABENCH.zh-CN.md)；自定义 JSONL benchmark 见
[benchmark 适配](BENCHMARK-ADAPTERS.zh-CN.md)。Agent 运行时是外部依赖，
**不随本仓库分发**。

配好之后先体检，再跑实验：

```bash
.venv/bin/python scripts/check_env.py --cell fdabench
```

---

## Agent 运行时

被迭代的 harness 本身也是外部依赖。至少装一个：

| harness | 安装方式 | 定位方式 |
| --- | --- | --- |
| **opencode** | 官方安装脚本 | `PATH`，否则 `OPENCODE_PREFIX`（默认 `~/.opencode`），否则 `HAI_OPENCODE_BIN` |
| **codex** | 官方 CLI | `PATH`；模型目录缓存来自 `HAI_CODEX_MODELS_CACHE`（默认 `~/.codex/models_cache.json`） |
| **pi** | `npm install @earendil-works/pi-coding-agent` 到 `<repo>/.pi-agent` | `PI_AGENT_BIN`，否则 `<repo>/.pi-agent/node_modules/.bin/pi` |

pi 还有一处额外作用：Harness Query 会读 npm 包自带的文档
（`.pi-agent/node_modules/@earendil-works/pi-coding-agent/docs/`）作为
`local_documentation` 证据。没装 pi 时该证据缺失，对应的测试会 skip。

opencode 与 codex 的官方文档快照已经 vendored 在 `assets/docs_cache/`，无需联网。

---

## 隔离说明

FDABench 的 rollout 采用本地无根隔离（`local_rootless_rollout=True`）：
每个任务独立工作目录，GT 文件锁在沙箱外，verifier 在沙箱外校验。
