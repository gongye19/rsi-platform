# CRMarenapro 接入

接入同一套 **DataAgentBench / CRMarenapro 13 题**，使用原始 `query.json`、六个数据库和官方 `validate.py`。
不导入 Harness² 或 RRSI 的算法代码。数据库文件从现有 checkout 复制到每个独立 trial 的只读输入目录；
PostgreSQL 复用已导入且指纹固定的数据库，通过只允许专用只读身份的临时端口访问。

默认划分沿用 RRSI：query1–query10 训练，query11–query13 测试。
这些留出题在之前的 Harness²/RRSI 工程实验中已出现，因此属于工程留出集，不能宣称全新盲测。
配置文件是 `configs/crmarenapro_split.json`。官方评分为二值结果，与 HarnessLens 的 pass@1/pass@2 兼容。

## 本机配置

公司独立实例的部署边界、记录位置与远端数据接通条件见 [公司业务 Agent 实验部署](COMPANY-EXPERIMENT.zh-CN.md)。

组件边界与当前开放范围见 [OpenCode 1.18.32 组件协议](OPENCODE-COMPONENTS.zh-CN.md)。
固定配置的候选修改会在启动前报错，不再通过覆盖候选配置来静默忽略。

```bash
cd /path/to/harnesslens
uv pip install --python .venv/bin/python -e '.[crm,dev]'
.venv/bin/python scripts/check_env.py --cell crm --harness opencode
.venv/bin/python scripts/run_crm.py --run-id crm-check
```

本机 `third_party/dataagentbench` 软链到已有数据，不重复下载，也不改动共享数据。
其他机器可在该目录放置同一 checkout，或设置 `HAI_DAB_ROOT`。
`configs/crm_postgres_fingerprint.json` 来自既有实验的规范快照；该接入不会自动重建或修改数据库。

本机 `.env` 为权限 0600 的 gitignored 文件；执行连接保留已有 GLM，分析使用 David AI GPT。两组在任务配置中明确选择，见 [模型连接](model-connections.zh-CN.md)。主要选项：

| 变量 | 用途 |
| --- | --- |
| `HAI_EXECUTION_API_KEY` / `HAI_EXECUTION_BASE_URL` | 执行接口凭据与地址 |
| `HAI_ANALYSIS_API_KEY` | 分析连接的独立凭据 |
| `HAI_EXECUTION_MODEL=crm/glm-5.2` | 求解模型；provider 名称 crm 只用于本地路由 |
| `HAI_ANALYSIS_MODEL=david/gpt-6.2-sol` | 分析、编辑等演化角色的模型 |
| `HAI_OPENCODE_BIN` | 本机固定的 OpenCode 1.18.32 官方 macOS ARM64 二进制 |
| `HAI_OPENCODE_VERSION=1.18.32` | 启动前校验版本；不匹配立即停止 |
| `HAI_CRM_RUNTIME_ROOT` | `runtime/opencode-1.18.32`；运行时供 agent 只读访问 |
| `HAI_OPENCODE_LEGACY_CLI=0` | 使用当前版本的 `--pure --auto` CLI |
| `HAI_CRM_POSTGRES_PORT=55432` | 宿主侧 PostgreSQL 端口，agent 只能连接临时受限代理 |

默认原生求解使用 OpenCode + macOS Seatbelt；另可配置 [Python／HTTP 业务 agent](BUSINESS-AGENTS.zh-CN.md)。
固定版本与官方发布包校验和记录在 `configs/opencode-runtime.json`。
执行 `.venv/bin/python scripts/install_opencode.py` 可安装同一 macOS ARM64 二进制。
显式路径优先于 PATH；求解、分析、编辑和环境检查共用同一个解析器。
该切换适用于 HarnessLens 新实验；旧 RRSI/Harness² 运行时和已有实验保留，不能跨版本复用旧 trial。
原生 GLM 的 thinking 关闭，与现有本地实验配置一致；
这不是论文默认 DeepSeek/high-reasoning 实验的直接复现。比较方法时应冻结模型、运行时、数据、预算及拆分。

## 冒烟与正式实验

真实模型接口可用后，先运行 query1 的基线和一个指令传递探针：

```bash
.venv/bin/python scripts/run_crm.py --run-id crm-smoke-new --smoke --probe-candidate
```

它会在 `runs/crm_checks/<run-id>/` 保存环境指纹、预检、答案、完整 API 请求/响应、用量和评分。
探针只验证指令加载，不作为改进收益。明确认证或额度错误会停止；失败记录保留，修复后使用新 run-id。
成功的 trial 可以在相同环境下复用；配置或源数据变化会拒绝复用。

正式 TRAIN 入口：

```bash
scripts/run_e2e.sh --run-id crm-train-001 --cell crm --harness opencode
```

默认 10 题 × 2 次基线，候选继续使用原有行为诊断、配对筛查与确认协议。
总会话预算由 `HAI_TOTAL_CREATION_BUDGET` 控制，默认 200。此接入没有更改晋升算法。
训练结束后使用冻结提交，在另外 3 题上比较初始版本与选定版本：

```bash
.venv/bin/python run_test_baseline.py --run-id crm-test-001 --benchmark dab-crmarenapro --harness opencode
.venv/bin/python run_test_candidate.py --run-id crm-test-001 --benchmark dab-crmarenapro --harness opencode \
  --patch-json runs/train/crm-train-001/submission/final.json
```

测试题、评分器和参考答案不会放进训练探索输入。agent 无法读取宿主评分文件或修改输入数据。
官方 grader 的完整诊断保存为宿主 `grading.json`，提供给演化角色的轨迹只包含通过状态与评分器指纹，避免诊断文字泄露答案。

## 本次验证记录（2026-11-23）

- 13 题及六份数据文件与既有 manifest 一致；PostgreSQL 内容与规范快照一致。
- 六个数据库的 schema 查询通过；源文件写入、评分器读取、管理端口连接和 PostgreSQL 写入均被拒绝。
- 本地模拟 provider + 真实 OpenCode：验证数据库工具、官方 grader、候选 instructions/system prompt、skill 发现及正文加载、配对 seed 和 token 记录。
- 模拟响应测试不代表真实解题成绩。真实智谱请求返回 HTTP 429 / 1310，提示周/月使用上限；接口返回的重置时间为 2026-11-25 20:54:20。
- 尚未运行完整训练或三题留出评测。

## OpenCode 版本对齐（2026-11-24）

已与业务端对齐至 1.18.32，安装包及二进制 SHA-256 均已验证。
官方文档缓存同步至 `v1.18.32` 标签；旧 `config.schema.json` 仅作归档，不再进入当前文档证据。

- CLI + 真实 CRM 工具/评分器通过：`runs/opencode-1.18.32-crm.log`。
- HTTP `serve` 的事件订阅、会话消息导出和模型请求/响应代理通过：`runs/opencode-1.18.32-http/`。
- 编辑器在 Seatbelt 沙箱内的 `--pure --auto` 调用、trace 与用量记录通过：`runs/opencode-1.18.32-editor/`。沙箱已补充系统时区数据的只读访问，并将临时文件限制在当前工作区。
- 以上使用本地模拟模型，只证明运行时与采集链路兼容，不代表真实解题成绩。
