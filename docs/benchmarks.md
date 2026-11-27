# Environment Setup

The platform ships the native FDABench benchmark plus configuration-driven
custom JSONL benchmarks. FDABench data is prepared locally with
`scripts/prepare_fdabench.py`; see the [FDABench guide](FDABENCH.zh-CN.md).
Agent runtimes are external dependencies and are not distributed with
HarnessLens. Run `scripts/check_env.py` after setup; it validates the exact
files and executables required by the selected environment.

## Agent runtimes

Install at least one target harness:

| Harness | Resolution |
| --- | --- |
| OpenCode | `PATH`, `OPENCODE_PREFIX`, or `HAI_OPENCODE_BIN` |
| Codex CLI | `PATH`; optional model cache via `HAI_CODEX_MODELS_CACHE` |
| Pi | `PI_AGENT_BIN`, or `.pi-agent/node_modules/.bin/pi` |

OpenCode and Codex documentation snapshots used during harness exploration are
vendored under `assets/docs_cache/`. Pi documentation is read from its installed
npm package.

## Isolation

FDABench uses per-task local workspaces with ground-truth data and grading
outside the agent sandbox. Use the preflight checker before every new
environment/harness pair:

```bash
.venv/bin/python scripts/check_env.py --cell fdabench --harness opencode
```

[中文版本](benchmarks_zh.md)
