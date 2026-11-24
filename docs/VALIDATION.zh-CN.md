# 本机交付验证（2026-11-25）

本仓库是在上游 `jhxu5214/HarnessLens` 的 MIT 实现上增加的内网适配，保留上游许可证和原优化控制流程。

| 范围 | 结果 |
| --- | --- |
| 合并回归：控制器、预算、发现、分析、候选、trace、业务适配、CRM、平台、初版、并发恢复、16组件及本地集成 | 657 passed，13 skipped，3 deselected |
| OpenCode版本/本机模拟集成测试集：包括16组件原生、Python、HTTP及故障注入（已含于上行） | 16 passed |
| OpenCode发现契约/文档内容的专项回归 | 4 passed，26 deselected |
| 13题最终免费预检：六数据源可读、官方校验器/源数据/管理端口/数据库写入隔离 | 通过 |
| Linux ARM64 完全断网：Python 锁定依赖、OpenCode 1.18.32 安装 | 通过 |
| Linux ARM64：服务队列/停止恢复、HTTP/Python 适配、通用 benchmark、组件协议 | 78 passed，2 skipped |
| Linux ARM64 断网：新增可选初版、冻结、继承、HTTP 基线/留出及包回载 | 13 passed，2 Python cases deselected |
| 前端静态检查、TypeScript/生产构建 | 通过 |
| 前端谱系/指标/布局与只读分享测试 | 38 passed |
| 实际 Next.js→平台 API：创建草稿、状态、真实记录入口、拒绝启动 draft | 通过 |
| 真实 OpenCode 1.18.32 + 本机 CRM 数据库 + 本地模拟模型（空初版/非空初版） | 2 passed |
| Python/HTTP CRM 接入 + 本地模拟模型 | 2 passed |
| 新建隔离 PostgreSQL 17.7：导入数据、六表规范指纹 | 通过 |
| systemd API/Worker 生成文件的 Linux 语法验证 | 通过 |
| Git 提交文件：真实凭据、生成记录/依赖/数据误提交检查 | 通过 |

Linux 验证使用本机临时验证环境；交付和部署流程无需 Docker。验证环境开启了 bubblewrap 所需能力；普通受限环境的 namespace 检查会正确失败。公司 Linux 主机是否允许这些能力仍需运行预检确认。Linux x64 已准备校验固定的运行时归档和锁定依赖 wheels，本机未实测 x64 执行。
Linux各行是前一交付的基础能力结果；本次16组件运行集成在macOS完成，不宣称已在公司Linux或公司业务服务上实测。

未调用真实付费模型，未连接公司业务服务，未运行13题真实优化性能实验。模型响应均为本地模拟；上述通过不构成进化效果或业务准确率证明。

本轮故障注入覆盖临时限流恢复、额度错误立即失败、重试次数、Retry-After、流中断、结束标记后延迟断开、输入管道阻塞超时及启动阶段失败即停止。当前本机13题的最终配置和一条命令入口见 [CRM-LOCAL-RUN.zh-CN.md](CRM-LOCAL-RUN.zh-CN.md)。
新增实测覆盖16类的配置/请求/触发证据、子Agent独立会话、工具可见性、权限拒绝、工具截断、原生Command、插件Hook、自定义工具和stdio MCP。测试还验证越界模型/权限修改、错误参数不会进入普通评分，并通过原编辑管线生成非提示词组件候选；原晋升与配对确认算法不变。

全量上游测试还包含 BIRD、tau2、Terminal-Bench、Pi 等外部安装集成测试；这批依赖没有随本次13题交付安装，未计入上表，不能宣称整个上游套件已通过。原始本机日志在未提交的 `runs/` 中。
核心回归未收集BIRD、盲测外部数据、任务数据、tau2和全量跨运行时发现测试文件；另明确排除了两个依赖完整retail资源的指纹测试及一个需要其环境的Clash启动测试。发现专项仅运行OpenCode且不加载其它题库，未把缺失外部环境的用例伪装成通过。

待内网完成：真实 HTTP/trace 映射与回执、隔离 CRM 数据/工具可达性、公司模型凭据及配额、Linux 沙箱策略和进程托管。按 [INTRANET.zh-CN.md](INTRANET.zh-CN.md) 先冒烟，再把 profile 改为 ready 后启动。
