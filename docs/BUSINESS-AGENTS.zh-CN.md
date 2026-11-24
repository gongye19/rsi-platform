# Python／HTTP 业务 agent 接入

HarnessLens 现在可以通过配置调用现有 Python 函数或同步 HTTP POST/JSON 接口，业务源码无需引入 HarnessLens。
调用适配位于 `harnesslens/harnesses/business_agent.py`，通用执行生命周期位于 `harnesslens/evaluation/business_runtime.py`。
CRM 和配置驱动的 JSONL benchmark 共用训练、候选预检、评分、独立测试和恢复路径。
新增问答题库可按 [通用 benchmark 接入](BENCHMARK-ADAPTERS.zh-CN.md) 配置；特殊交互环境需实现 benchmark 适配器。

`--harness opencode` 仍指定优化器用于分析、编辑等工作的运行时；实际解题的业务 agent 由 `--agent-config` 独立指定。
不传这个参数时，继续使用原来的 OpenCode 求解器。

## Python 函数

复制并修改 [示例配置](../examples/agents/python.toml)。例如已有函数为
`business_agent.api.solve(question, config_dir)`，返回 `result.text`、`metrics.total_tokens` 和 `messages`：

```toml
[agent]
type = "python"
name = "my-business-agent"
function = "business_agent.api:solve"
python = "/path/to/business-project/.venv/bin/python"
python_paths = ["/path/to/business-project"]
timeout = 600
answer_path = "result.text"
usage_path = "metrics.total_tokens"
trace_path = "messages"
# pass_env = ["BUSINESS_MODEL_KEY"]

[agent.arguments]
question = "{prompt}"
config_dir = "{harness_dir}"

[capabilities]
channels = ["instructions_rules"]
```

只映射原函数已有的关键字参数。同步函数、异步函数、JSON 对象、dataclass 和支持 `model_dump` 的返回值均可使用。
调用在指定解释器的独立进程中执行，支持自己的虚拟环境和包路径。相对路径以 TOML 所在目录为基准。
超时会终止本次调用的进程组；stdout、stderr 和响应保留在本次执行目录。

默认 `sandbox="auto"`：macOS 使用 Seatbelt，Linux 需要 bubblewrap。
业务源码及声明的资源只读，本次任务目录可写；source/harness 在子进程中受写保护，宿主评分文件不交付。
若业务函数需要额外本地资源，用 `read_roots` 声明；显式 `sandbox="none"` 会关闭文件隔离。
凭据通过 `pass_env` 指定变量名，父进程的其他模型密钥不会自动传入。

## HTTP API

复制并修改 [示例配置](../examples/agents/http.toml)：

```toml
[agent]
type = "http"
name = "my-business-service"
revision = "v1"
url = "https://your-business-service.example/solve"
token_env = "BUSINESS_AGENT_TOKEN"
timeout = 600
answer_path = "data.answer"
usage_path = "data.usage.total_tokens"
trace_path = "data.messages"

[agent.body]
question = "{prompt}"
# 若已有服务支持幂等字段，可映射：
# request_id = "{request_id}"

[agent.body.options]
instructions = "{harness_files}"
```

`token_env` 发送 Bearer 认证；自定义敏感头可配置 `[agent.headers_env]`，例如 `X-API-Key="BUSINESS_API_KEY"`。
固定非敏感头使用 `[agent.headers]`。认证头不写入请求记录，不跟随重定向，不自动重试。
本机服务可用 HTTP，远程服务使用 HTTPS。当前支持一次 POST 返回最终 JSON，异步提交／轮询接口还需要增加调用协议。

HTTP 超时只代表客户端停止等待，不能保证远端任务已取消。已有的 `request_id` 幂等能力可以避免手动恢复时重复执行。
本地成功结果会缓存；失败响应及状态保留，不能用零分代替接口故障。
`revision` 用于区分远端部署版本；框架无法独立证明远端代码、数据或配置没有变化。

## 参数映射和交付内容

| 占位符 | 内容 |
| --- | --- |
| `{prompt}` | 候选常驻指令 + 公开任务与工具使用说明 |
| `{instructions}` | 候选常驻指令 |
| `{harness_dir}` | 本次候选 project 目录，仅本机或共享文件系统可访问 |
| `{harness_files}` | `{"home": {"路径": "正文"}, "project": {"路径": "正文"}}`，用于传完整候选文件 |
| `{harness_digest}` | 已交付文件的内容指纹 |
| `{workspace}` | 本次任务的独立目录，公开 source 在其下 |
| `{task}` / `{task_id}` | 公开任务对象／任务 ID，不含参考答案及 grader |
| `{request_id}` / `{trial_id}` | 固定调用身份／trial 标识 |
| `{seed}` | 新旧候选配对使用的相同 seed，只有接口本来支持时才映射 |
| `{scope}` | TRAIN 或 TEST |
| `{model}` / `{steps}` / `{timeout}` | 运行配置中的名称及限额 |

整个值等于占位符时保留对象、列表、数字类型；字符串内嵌占位符时转为文本。
返回字段支持 `data.answer` 这样的路径，以及 `items.0.text` 这样的列表索引。`answer_path=""` 表示整个返回值就是答案。

远程服务应接收 `{harness_files}`，不能直接读取客户端的 `{harness_dir}`。
CRM 的数据库工具需要在业务 agent 的环境中可用；远程机器不能直接使用本机 localhost 的数据库代理。

## 轨迹、用量和加载证据

默认 `trace_path="messages"` 接收常见 conversation 消息：`role` 为 user/assistant/tool/system/developer。
已有 OpenCode 原生消息 `[{"info":...,"parts":...}]` 可设置 `trace_format="opencode"`，适配层会转换真实的文本、工具调用和结果。

默认 `cost_metric="tokens"`，要求 `usage_path` 返回有效 token 数；缺失时停止，不补零。
若原接口不返回用量，可显式选择 `cost_metric="wall_seconds"`，保留 `total_tokens=null`，另外记录实际耗时。
HarnessLens 的总预算仍以 interaction/session 计量，耗时没有被冒充为 token。

只返回字符串的已有函数也能做执行验证：

```toml
[agent]
type = "python"
function = "business.api:solve"
answer_path = ""
cost_metric = "wall_seconds"
require_trace = false
[agent.arguments]
question = "{prompt}"
```

但行为感知演化需要内部行为证据。要通过候选 channel preflight，可配置 `api_calls_path` 指向业务 agent **已有的真实模型请求／响应记录**，或使用下述独立 trace 接口。
其格式为列表，每条至少含 `request` 和 `response`；也可含 `upstream_status`、`usage`。
这与适配器保存的 Python／HTTP 传输回执是两类记录：发送成功不等于系统提示词、skill 或工具配置已经加载。
缺少模型请求证据时，可执行和评分，但候选预检不会据此通过，也不会被晋升。

`[capabilities].channels` 只声明业务 agent 已有的能力。默认仅 `instructions_rules`；原服务若支持原生 skill/system prompt 等，可再声明
`skills`、`system_prompt`、`agent_definitions`、`project_instructions`。声明不会给远端服务添加新功能，实际加载仍须用证据验证。

组件目录固定为 [16类编辑组件＋5类仅提案](OPENCODE-COMPONENTS.zh-CN.md)。当前业务交付适配实现了四类 prompt/skill/agent 加载机制；
这是执行器当前的实现范围，不是由 benchmark 名称决定的搜索白名单。模型根据实际接口与运行证据判断哪些机制有效；
`project_instructions` 作为旧别名规范化到 `instructions_rules`。
声明原生 system prompt/Skill/Subagent 时，必须交付 `{harness_files}` 或 `{harness_dir}`，
并启用 `require_harness_receipt=true`（响应中的 `harness_receipt`）或独立 `[trace]`。
还需要业务端的真实 `runtime_report`，格式为 `harnesslens.channel-load-report.v1`；
内联返回可设置 `runtime_report_path`，默认不把本机准备好的文件当作远端运行报告。
系统提示词保存在 `opencode.json`，业务端需要原生加载，不能将其降级为普通用户指令。

## 业务接口只返回答案：独立 trace 接口

示例见 [http-trace.toml](../examples/agents/http-trace.toml)，同样适用于 Python 函数。
已有业务调用完成后，适配器按配置执行一次带认证的 GET，不重新执行业务任务。
`trace.url` 可包含 `{request_id}`、`{harness_version}`；若用 `{session_id}`，
还需配置 `session_id_path` 从业务响应取出 session。占位符只允许在 URL 路径中，值会编码。
认证使用 `trace.token_env` 或 `trace.headers_env`；不跟随重定向，不自动重试。

这个 URL 指向你已有的 trace 服务，需要聚合 OpenCode 会话和 provider 调用记录。
它不是 OpenCode 原生 `/session/.../message` 的别名，也不会从答案中补造轨迹。
只读 OpenCode 会话消息还不足以验证实际模型请求；聚合接口应返回：

```json
{
  "request_id": "本次请求ID",
  "session_id": "ses_...",
  "harness_version": "本次版本",
  "harness_digest": "本次交付文件摘要",
  "opencode_version": "1.18.32",
  "component_protocol": "harnesslens.opencode-components.v1",
  "messages": [{"info": {"role": "assistant"}, "parts": []}],
  "api_calls": [{"request": {}, "response": {}, "upstream_status": 200}],
  "usage": {"total_tokens": 123},
  "runtime_report": {"schema": "harnesslens.channel-load-report.v1", "harness": "opencode"}
}
```

上例中的空消息/请求/报告仅展示结构，实际必须返回完整记录和加载内容。
六个身份字段不匹配或缺失会拒绝结果；单独的 trace 原件保存在 `collected_trace.json`，并绑定到传输回执。
还应在业务参数映射中发送 `{request_id}`、`{harness_version}`、`{harness_digest}`，让服务关联本次执行。
`{component_protocol}` 是包含完整目录的 JSON 对象，服务回执中填写其 `schema` 字符串。
仅发送成功或仅有回执仍不能通过通道生效验证。

## 检查与运行

仅检查配置格式，不调用业务服务：

```bash
.venv/bin/python scripts/check_business_agent.py --config examples/agents/python.toml
```

显式调用一次已有业务 agent（会使用它的真实资源）：

```bash
.venv/bin/python scripts/check_business_agent.py --config /path/to/agent.toml \
  --prompt "你的公开测试问题" --harness-dir /path/to/harness --output ./runs/agent-check-new
```

接入同一套 CRM 10/3 拆分：

```bash
.venv/bin/python scripts/check_env.py --cell crm --harness opencode --agent-config /path/to/agent.toml
scripts/run_e2e.sh --run-id crm-business-001 --cell crm --harness opencode --agent-config /path/to/agent.toml

.venv/bin/python run_test_baseline.py --run-id crm-business-test --benchmark dab-crmarenapro \
  --agent-config /path/to/agent.toml
.venv/bin/python run_test_candidate.py --run-id crm-business-test --benchmark dab-crmarenapro \
  --agent-config /path/to/agent.toml --patch-json runs/train/crm-business-001/submission/final.json
```

也可使用环境变量 `HAI_AGENT_CONFIG`。恢复同一次实验必须使用相同配置、源码、数据和拆分；改变设置应新建 run-id。
原 OpenCode 求解模式仍是默认值。这次代码验证使用了本地 Python／HTTP 服务与模拟模型，没有运行正式优化实验或调用未提供的业务地址。
