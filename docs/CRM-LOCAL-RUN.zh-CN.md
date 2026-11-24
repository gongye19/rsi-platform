# 本机13题实验启动单

本轮使用已有 CRMarenapro 13题及配套官方 validator，**不依赖尚未实现的开放问答模型评分器**。
本机原生 OpenCode 1.18.32、数据和六表 PostgreSQL 指纹已经预检。原生 CRM 的本机隔离当前使用 macOS Seatbelt；Linux 内网业务 HTTP 接入见 INTRANET.zh-CN.md。

## 明天 API 恢复后

在仓库根目录运行：

```bash
.venv/bin/python scripts/run_crm_experiment.py --run-id crm-20261125-01 --run
```

这条命令依次执行：

1. 免费本机预检：数据、表结构、版本及只读隔离。
2. 付费 query1 冒烟：空初版和带指令候选各一次，验证答案、trace、token 用量和候选交付。
3. TRAIN：query1–10，每题基线重复2次，按原 HarnessLens 流程执行发现、分析、编辑、配对确认及选优。
4. 冻结最终版本后才执行 TEST：query11–13，初版与选定版本分别评测。最终仍是 v0 时复用同一份 TEST 初版结果，不制造重复测量。

任一步失败均停止后续步骤。并非在基线失败时强行把故障记成零分，或直接跳到最终评测。
这些3条留出题曾用于工程验证，不宣称是从未接触的新盲测。

只验证模型恢复、不开始完整优化：

```bash
.venv/bin/python scripts/run_crm_experiment.py --run-id crm-20261125-01 --smoke-only
```

确认成功后使用同一编号加 `--run`，已完整且指纹一致的冒烟记录会被复用。
不加这两个参数时**只做免费预检，不发送模型请求**：

```bash
.venv/bin/python scripts/run_crm_experiment.py --run-id crm-readiness-01
```

## 固定启动配置

默认读取 `configs/experiments/crm-local.toml`，私有 API/model 设置从 `.env` 读取。与公司 HTTP 草稿配置分开：本次不需要公司的接口地址。

| 设置 | 本轮值 |
| --- | --- |
| 初始 Harness | 默认空 v0；可在私有 profile 设置 initial_harness |
| 组件范围 | 16类全纳入探索；模型自行选择，逐项经过加载/请求/触发验证 |
| TRAIN 创建预算 | 200，包含20次 TRAIN 基线会话；不是费用或 token 上限 |
| 任务并发上限 | 4 |
| 分析角色并发 | 2 |
| 跨本机代理进程的模型请求总并发 | 4 |
| CRM 单 trial 总超时 | 900秒 |
| 分析／编辑会话额外总超时上限 | 1200秒 |
| 上游 HTTP/socket 超时 | 180秒 |
| 单请求重试预算 | 420秒；整个会话另有总超时 |
| 等待模型并发槽 | 最多120秒 |
| 上游单请求总尝试次数 | 最多4次，含首次 |

冒烟另用2次会话，TEST另用6次或12次会话，不包含在 TRAIN 的200次预算中。所有实际请求和用量分别保留。
这些并发是客户端上限，不代表套餐保证允许4并发。恢复后由真实冒烟/运行确认实际限制；持续限流时把私有 profile 的任务和模型请求并发降到2，并使用新实验编号。

## 失败处理与恢复

- 模型请求仅对临时限流、5xx、连接异常做有限指数退避，带随机错峰并尊重合理 Retry-After。
- 智谱1302/1305可退避；1113、1308、1309、1310等余额、套餐和周期额度错误立即停止等待处理。含义见[官方错误码](https://docs.bigmodel.cn/cn/faq/api-code)。
- 正在重试的日志不作为终局故障，避免提前杀掉本可恢复的请求；终局失败则尽快终止该 Agent。
- 流式响应中断或缺少结束标记会保存部分响应并标记基础设施错误，不重新拼接或悄悄重放已开始的流。
- stdin、任务和分析进程都有超时与清理；Ctrl-C/SIGTERM 清理本次拥有的进程，记录保留。
- 完成的阶段和完整 trial 使用原有缓存和检查点。结果不明、已有失败 trial 或不兼容指纹时会明确拒绝静默重跑；保留原记录，解决问题后按报错决定新建实验。
- 超时/鉴权/额度故障不作为候选正常错误率来选优，也不触发“试到答对为止”。候选未获采用时继续使用父版本。
- 组件静态校验或已识别的插件/工具参数执行错误，在预检阶段拒绝候选并保留父版本；不把无评分的失败记成普通答错。
- 业务 HTTP 请求继续保持不自动重放；这里的请求级重试针对本机模型代理，不擅自重复业务操作。

`--run` 不会因为日期到了自动启动；必须在 API 确认恢复后显式执行。

## 看哪里

- `runs/local_experiments/<id>/launcher.log`：完整启动与阶段日志。
- `runs/local_experiments/<id>/stage.json`：当前大阶段及成败。
- `runs/train/<id>/controller_state.json`、`creation_budget.json`：优化进度与预算。
- `runs/train/<id>/submission/final.json`：选定版本及完整 Harness 包引用。
- `runs/local_experiments/<id>/result.json`：完成后汇总 TRAIN 和 TEST 产物位置。

尚未进行真实付费优化。当前通过的是本机环境检查、真实 OpenCode 加本地模拟模型的集成验证及故障注入；不能据此承诺真实 API 已恢复、实际吞吐或优化效果。
