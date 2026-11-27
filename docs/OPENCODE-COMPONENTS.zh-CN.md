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
原始附件和工具返回数据固定；第12类可优化处理/上下文策略，不授权篡改原始输入。工具截断的完整输出仍由原生运行时保存。
模型、Provider、采样参数和总预算上限固定；执行步数可在固定上限内优化（当前本机上限40），不能借此提高总预算或超时上限。

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

当前本机执行器已接通16类的加载和验证机制，默认全部纳入模型探索；不再有只允许四类的代码上限。
业务 Python/HTTP 交付也接受16类，接收端可使用同一个公共加载函数。换题库不会自动改变组件边界。

## 启动时设置边界

实验 TOML 可以省略 `[components]`，默认允许16类；也可以显式填写：

```toml
[components]
allowed = ["*"]
denied = []
experimental_fields = ["primary_tools", "continue_loop_on_deny", "mcp_timeout"]
```

例如禁止改权限和MCP：`denied = ["permissions", "mcp_servers"]`；只研究部分组件则把 `allowed` 换为具体组件ID数组。
允许范围取 `allowed - denied`，业务接入再与服务 `[capabilities].channels` 取交集。
同一实验中不能改配置继续使用旧缓存；改边界应使用新 run_id。直接CLI也可通过 `HAI_COMPONENT_POLICY` 传入同结构JSON；平台profile优先。
这些配置是边界，不要求模型把16类都判为可修改，也不要求一轮全部改动。

运行顺序：加载实验边界 → 基线真实请求收集工具目录 → 模型检查版本、文件、加载机制及接口 → 生成候选 → 静态校验 → 单题生效预检 → 原有配对评测和选优。
工具名称、参数和说明来自 TRAIN 基线实际请求；不会因为外层任务使用SQL CLI而隐去原生工具。

| 组件 | 已实现的加载／验证路径 |
| --- | --- |
| 常驻规则、系统提示词 | 原生AGENTS.md/instructions、agent prompt；检查真正的system/developer请求 |
| Skill | 版本化文件和发现路径；检查真实工具目录中的描述及实际加载 |
| Agent定义、执行调度 | 编译原生Agent文件/配置；主Agent、Subagent、默认Agent、步数和嵌套深度；保留会话ID、Agent名和父子关系 |
| 工具描述、工具参数指导 | 固定原生 `tool.definition` 桥；只修改描述，保留参数结构及原校验器；核对实际请求中的工具Schema |
| 工具可用性、权限 | 原生配置；旧tools标志转为规范权限表达，避免通配规则意外重新开放工具；检查实际工具目录和运行配置 |
| Command | 原生命令文件/配置；本轮固定调用 `harnesslens_run`，默认模板 `$ARGUMENTS`；候选可改模板、Agent、subtask，保留问题参数；未触发的其它命令不能冒充预检通过 |
| 参考资料 | 捕获本地资料目录并配置 `references`；目录/说明进入系统加载目录，由read等工具按需读取；不把“目录可见”称为正文已读 |
| 上下文管理 | 原生compaction、近期保留、tool_output及attachment.image字段；保留实际配置、截断原文及压缩触发事件 |
| 自定义工具 | 原生JS/TS工具及辅助脚本；随候选交付，在同一沙箱中执行，核对模型实际看到的工具 |
| 插件执行逻辑 | 原生本地插件；记录模块初始化、具体Hook调用和错误，仍禁止借Hook改固定模型/采样或实验禁止的配置 |
| MCP接入 | 原生本地stdio/已配置网络边界内的remote服务；核对实际暴露的MCP工具，不以配置文件存在代替连接成功 |
| 实验性策略 | 只接受启动时列出的1.18.32行为字段；遥测和Provider访问策略仍归原五类仅提案项 |

配置字段、Agent frontmatter和候选文件都会做静态校验，不支持的字段提前报错，不再被静默覆盖。
捕获的配置使用JSON；生产配置若为JSONC，应先去掉注释转为JSON。原算法每个候选至多改变一种全局指令通道的约束继续保留，不要求同一候选同时修改16类。
默认脚本/插件依赖随仓库提供校验固定的离线JS依赖包，不要求实验时联网安装npm包。
额外依赖、远程Skill和git参考资料应先准备成可达的固定资源；本机沙箱的外部网络边界不会因开放MCP或权限组件而自动扩大。
当前13题没有图片附件，所以附件处理可加载配置，但不宣称本轮已触发图片处理。

预检区分 `runtime_config_loaded`、`request_catalog`、`model_request`、`runtime_triggered`。
配置已生效不等于某个按需行为已经执行，例如小上下文未必触发压缩；这些都不等于组件有独立收益。
候选静态无效或已识别的组件执行错误，在预检阶段拒绝并保留父版本，不进入普通答题评分；额度、网络等基础设施错误暂停实验。

## 加载证据和交付

系统提示词保存在原生配置中，不合并到 AGENTS.md。预检检查模型请求中的 system/developer 部分，
把相同文本放在用户消息里不能通过系统提示词验证。
匹配必须读取解码后的请求文本，保留换行、引号、反斜杠和 Unicode；不能在
`json.dumps(request)` 的转义结果中搜索原文。原生组件预检与通用预检共用这条
文本提取路径，兼容 messages/content 文本块及 Responses 的 instructions/input，
并排除 user_sim 请求，避免将模拟用户的文本当作业务 Agent 的生效证据。
业务返回的加载回执须匹配 request_id、session_id、Harness版本、文件摘要、OpenCode版本和组件协议；
回执还需结合真实模型请求和生效检查，不能单独作为已触发证明。

新候选快照保存 `component_protocol.json`。最终选定版本输出内容寻址的 `submission/harness-<sha256>.json`，
包含完整 workspace、legacy manifest、组件协议及实验加载契约，`final.json` 引用包路径和摘要。
该包是本地交付产物，包含候选文件；不会自动部署到业务服务。

## 本次验证

测试覆盖：启动边界、模型探索不被四类白名单替换、真实基线工具目录、原五类仅提案、字段归属、未知/固定配置拒绝、父版本保留及内容包校验。
本地综合集成使用真实 OpenCode 1.18.32、CRM数据库、原生工具、stdio MCP与本地模拟模型：原生、Python和HTTP三种路径均逐项通过16类预检；另有模型/权限越界及错误参数的故障注入。
还实际检查了子Agent、权限拒绝、工具截断、Command、插件Hook、自定义工具和MCP调用；未调用真实付费模型，不构成解题成绩或进化效果证明。
实现依据为 [1.18.32配置源码](https://github.com/anomalyco/opencode/blob/v1.18.32/packages/core/src/v1/config/config.ts) 和 [插件API源码](https://github.com/anomalyco/opencode/blob/v1.18.32/packages/plugin/src/index.ts)，每个候选仍需本次运行证据。

2026-11-27 修复：CRM 8/5 实验两个多行 system_prompt 候选已经出现在真实请求，
但旧原生检查器对序列化 JSON 搜索原文，错误判为未加载。原始 trace 重放后两者
均通过接入检查。新增转义文本、content 文本块、Responses 与错误角色反例的回归；
真实本地 OpenCode 的多行 prompt 和原生/Python/HTTP 16 通道集成也通过。
历史实验记录不回写为“采用”或“有收益”，修复后的检查通过不替代 TRAIN 效果评测。
