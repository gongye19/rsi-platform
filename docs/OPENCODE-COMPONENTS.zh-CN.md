# OpenCode 1.18.32 组件协议

协议：`harnesslens.opencode-components.v1`。这是我们的业务分类，不是 OpenCode 官方模块数量。
代码定义在 `harnesslens/harnesses/opencode_components.py`，供其它程序读取的快照为 `configs/opencode-components.json`。

| 编号 | ID | 组件 | 1.18.32 对应的编辑内容 |
| --- | --- | --- | --- |
| 1 | instructions_rules | 常驻规则 | AGENTS.md、instructions 引用的指令 |
| 2 | system_prompt | 系统提示词 | agent.<name>.prompt、系统消息变换 |
| 3 | skills | Skill | 技能描述、正文、附属脚本及发现路径 |
| 4 | agent_definitions | Agent 定义 | 主 Agent/Subagent 的角色、描述、模式 |
| 5 | execution_policy | 执行与调度 | 默认 Agent、执行步数、子 Agent 嵌套深度 |
| 6 | tool_description | 工具描述 | 提供给模型的工具说明 |
| 7 | tool_parameter_description | 工具参数指导 | 参数描述及兼容原接口的 Schema 表达 |
| 8 | tool_availability | 工具可用性 | 各 Agent 可使用哪些已有工具 |
| 9 | permissions | 权限规则 | 按操作、参数、路径配置允许或拒绝 |
| 10 | commands | Command | 命令模板、指定 Agent 等 |
| 11 | reference_sources | 参考资料接入 | references、资料说明与加载方式 |
| 12 | context_management | 上下文管理 | 压缩、近期上下文保留、工具输出截断、附件处理 |
| 13 | custom_tools | 自定义工具 | 工具实现及辅助脚本 |
| 14 | plugin_tool_system | 插件执行逻辑 | 调用前后 Hook、消息处理等执行逻辑 |
| 15 | mcp_servers | MCP 接入 | MCP 服务和工具接入配置 |
| 16 | experimental_policies | 实验性策略 | 本次明确允许的 experimental 行为字段 |

原有五类继续仅提案，控制器禁止自动编辑：`model_provider`、`runtime_env`、`file_attachments`、`tool_return`、`diagnostic`。
原始附件和工具返回数据固定；第12类记录处理/上下文策略，不授权修改这些输入。当前 CRM 也不开放附件或截断配置。
模型、Provider、采样参数和总预算上限固定；执行步数等字段被分类为执行调度，不表示本次实验允许修改。

每个配置字段只有一个语义归属。`agent.*.prompt` 归系统提示词，`agent.*.steps` 归执行调度，
`agent.*.permission` 归权限，`agent.*.tools` 归工具可用性。插件只是承载文件时，不重复计算为第二个语义修改。
旧 `agent_tool_config` / `builtin_tools` 对应 `tool_availability`；旧 `compaction_config` 对应 `context_management`。
旧实验记录保留，协议升级不改写已有 trial 或历史通道 ID。

## 目录与本次准入

目录列出可描述的编辑面；实际准入必须同时满足版本支持、适配器实现、实验许可和生效验证。
静态物化契约标记为 `materializable`，不再冒充本次运行的模型请求证据。
实验禁止优先于通用准入白名单；五类仅提案不会因文档或模型建议而升级成可编辑。

`runtime_contract()` 提供实际加载器、固定覆盖、禁用功能和工具传输事实，不按 benchmark 名称预设可编辑目录。
Harness Query 模型结合源码/文档、运行探针和加载契约，逐项给出可修改机制或不可用原因；
程序保留模型的判断，再检查证据、实验边界和候选生效预检。模型没有判断可改的通道不会因历史白名单被自动添加。
也不会把 `documented` 声称自动升级成 `materialized` / `runtime_observed`。

当前原生 SQL-CLI 执行器实测实现的是常驻规则、系统提示词、Skill、prompt-only Subagent 这条加载路径。
这是当前执行器的实现/验证范围，不是为 CRM benchmark 规定的永久四类白名单。
其它机制需要相应执行适配和生效检查；模型发现支持并不等于其候选已通过验证。
业务 Python/HTTP 的 `[capabilities].channels` 描述服务接口实际可接收的能力，不代表框架已替它实现这些能力。
同一业务 Agent、相同运行配置换题库时，不应仅因 benchmark 名称改变搜索范围；换执行器、工具绑定或实验约束才可能改变结果。
Command 原生存在但仍缺本执行器的触发与检查器；上下文自动压缩在当前实验被禁用；插件、自定义工具和 MCP 继续受原实验边界约束。

候选中的固定配置在启动前拒绝，不再静默覆盖。检查同时覆盖 flat patch、每个 JSON 配置文件、交付文件与 Agent frontmatter。
当前 prompt-only Agent 文件只接受 description、subagent mode 和正文，不接受夹带模型、权限、工具、步数等字段。

## 加载证据和交付

系统提示词保存在原生配置中，不合并到 AGENTS.md。预检检查模型请求中的 system/developer 部分，
把相同文本放在用户消息里不能通过系统提示词验证。
业务返回的加载回执须匹配 request_id、session_id、Harness版本、文件摘要、OpenCode版本和组件协议；
回执还需结合真实模型请求和生效检查，不能单独作为已触发证明。

新候选快照保存 `component_protocol.json`。最终选定版本输出内容寻址的 `submission/harness-<sha256>.json`，
包含完整 workspace、legacy manifest、组件协议及实验加载契约，`final.json` 引用包路径和摘要。
该包是本地交付产物，包含候选文件；不会自动部署到业务服务。

## 本次验证

测试覆盖：模型探索结果不被历史四类白名单替换、保留不可用原因及原始证据级别、禁止通道不被重新开放、5项仅提案不可升级、字段唯一归属、配置与Agent文件拒绝固定项、
系统提示词角色验证、Python/HTTP 独立trace收集及身份不匹配拒绝、内容包摘要与篡改检测。
本地集成使用真实 OpenCode 1.18.32、CRM 数据库和官方评分器，模型响应由本地模拟服务提供，不代表真实解题成绩。
