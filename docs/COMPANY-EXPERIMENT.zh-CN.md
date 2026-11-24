# 公司业务 Agent 的实验部署

本轮 benchmark 固定为 `configs/crmarenapro_split.json` 中的13题：query1–10训练，query11–13工程留出。
这3题曾在既有工程实验中出现，不作为全新盲测。正式测试只在最终版本冻结后执行。

## 部署边界

- 实验平台：运行 HarnessLens、题库与宿主评分器，持有实验配置、预算、产物、trace和版本主记录。
- 业务实例：处理独立的评测请求。候选文件作为本次请求的配置输入，不覆盖代码库、全局 OpenCode 配置或线上默认版本。
- 测试数据/工具：与生产环境隔离。优先由实验侧提供独立只读入口；也可在隔离的评测环境准备同指纹副本。

跨实例优先使用 HTTP。Python 调用是 Worker 所在环境的本地函数调用，不能直接 import 另一台电脑上的函数。
若采用 Python，Worker 必须能访问公司包与依赖，可使用独立实例和只读代码挂载；不必给业务项目安装 HarnessLens。
跨机器 Worker 的调度和产物回传仍需部署支持，目前提供的 Python 执行器本身不是远程调度服务。

所有实验主记录保存在平台的 `runs/`，HTTP 接入不会在客户端调用中写远端代码库。
业务 OpenCode 运行必需的临时会话、状态和它原有的日志仍可能存在；独立临时目录和清理策略需要由业务运行接口支持。
不能仅凭客户端字段映射承诺远端“完全无写入”或“无资源竞争”。

## 需要填写的启动配置

使用 `examples/agents/company-http.toml` 作为草稿，在公司环境本地填入接口地址和已有字段映射即可，无需向本会话提供代码或密钥。
该草稿不是对现有公司 API 字段的断言，也没有配置为本机默认 agent。

| 配置 | 本轮安排 |
| --- | --- |
| Benchmark | CRMarenapro 13题，10/3拆分 |
| OpenCode | 1.18.32；平台运行时固定，业务端加载回执核对版本 |
| 调用 | HTTP为跨实例首选；Python作为可访问公司代码的本地Worker调用 |
| 候选传递 | 每次请求传版本、摘要、文件内容；不传客户端本机目录给远端 |
| 会话 | 每个trial使用独立会话和临时工作区，不复用真实用户会话 |
| 数据 | 指定隔离CRM测试数据环境，禁止写入生产数据 |
| 并发 | 首轮 rollout/analysis/provider 并发均设1，先验证query1 |
| 重试 | HTTP业务提交不自动重试；已有request_id幂等能力用于恢复关联 |
| 凭据 | 用环境变量；实验凭据与生产配额尽量分开 |
| 记录 | 平台runs目录保存请求回执、实际模型trace、评分和选定Harness包 |

低并发启动环境变量必须在启动Python之前设置，确保模块级配置读取到实际值：

```bash
export HAI_MAX_ROLLOUT_CONCURRENCY=1
export HAI_MAX_ANALYSIS_CONCURRENCY=1
export HAI_PROVIDER_MAX_CONCURRENCY=1
export HAI_AGENT_CONFIG=/absolute/platform/path/company-http.toml
```

原有训练重复次数和交互预算协议保留。交互预算计量session/trial，不等于模型HTTP请求数或金额上限。
后续再运行 `scripts/check_env.py --cell crm --harness opencode`，环境预检不会调用公司服务。

## 远端13题的当前接通条件

现有CRM执行器在平台准备 `source/query.py`、SQLite/DuckDB文件和只绑定127.0.0.1的PostgreSQL只读代理。
直接把当前问题与工具路径发给另一台机器，远端不会因此获得这些文件或数据库连接。

正式运行公司服务前必须接通一种测试数据方式：

1. 实验侧只读工具服务：业务Agent按本次请求使用该工具入口，数据库与查询审计留在实验侧。
2. 已有隔离测试环境：公司评测实例拥有与本次benchmark一致的数据和工具，通过环境身份与指纹核对。

本次没有新建网络入口、发布数据库端口、修改业务实例或假定现有接口支持某种工具协议。
远端数据准备/工具访问尚未连通时，只有调用适配和本地模拟验证，不应启动完整13题并宣称结果有效。

## Trace与验证

公司答案接口可以只返回答案，独立trace接口按request_id关联OpenCode session和真实provider请求/响应。
平台读取后保存自己的记录。回执核对Harness版本、摘要、OpenCode版本、组件协议和session身份，候选还需要实际加载预检。
如果已有trace接口与示例结构不同，在平台侧适配字段/聚合结果，不要求把所有日志塞进业务答案接口。

顺序是：离线配置检查 → query1联通/隔离/trace冒烟 → 完整10题训练 → 冻结版本 → 3题工程留出评测。
当前仍处于接入准备阶段，没有向公司服务发送请求，也没有启动付费进化实验。
