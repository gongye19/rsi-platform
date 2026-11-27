# 本机交付验证（2026-11-25）

本仓库是在上游 `jhxu5214/HarnessLens` 的 MIT 实现上增加的内网适配，保留上游许可证和原优化控制流程。

| 范围 | 结果 |
| --- | --- |
| 合并回归：控制器、预算、发现、分析、候选、trace、业务适配、平台、初版、并发恢复、16组件及本地集成 | 657 passed，13 skipped，3 deselected |
| OpenCode版本/本机模拟集成测试集：包括16组件原生、Python、HTTP及故障注入（已含于上行） | 16 passed |
| OpenCode发现契约/文档内容的专项回归 | 4 passed，26 deselected |
| Linux ARM64 完全断网：Python 锁定依赖、OpenCode 1.18.32 安装 | 通过 |
| Linux ARM64：服务队列/停止恢复、HTTP/Python 适配、通用 benchmark、组件协议 | 78 passed，2 skipped |
| Linux ARM64 断网：新增可选初版、冻结、继承、HTTP 基线/留出及包回载 | 13 passed，2 Python cases deselected |
| 前端静态检查、TypeScript/生产构建 | 通过 |
| 前端谱系/指标/布局与只读分享测试 | 38 passed |
| 实际 Next.js→平台 API：创建草稿、状态、真实记录入口、拒绝启动 draft | 通过 |
| systemd API/Worker 生成文件的 Linux 语法验证 | 通过 |
| Git 提交文件：真实凭据、生成记录/依赖/数据误提交检查 | 通过 |

Linux 验证使用本机临时验证环境；交付和部署流程无需 Docker。验证环境开启了 bubblewrap 所需能力；普通受限环境的 namespace 检查会正确失败。公司 Linux 主机是否允许这些能力仍需运行预检确认。Linux x64 已准备校验固定的运行时归档和锁定依赖 wheels，本机未实测 x64 执行。
Linux各行是前一交付的基础能力结果；本次16组件运行集成在macOS完成，不宣称已在公司Linux或公司业务服务上实测。

未调用真实付费模型，未连接公司业务服务，未运行真实优化性能实验。模型响应均为本地模拟；上述通过不构成进化效果或业务准确率证明。

本轮故障注入覆盖临时限流恢复、额度错误立即失败、重试次数、Retry-After、流中断、结束标记后延迟断开、输入管道阻塞超时及启动阶段失败即停止。
新增实测覆盖16类的配置/请求/触发证据、子Agent独立会话、工具可见性、权限拒绝、工具截断、原生Command、插件Hook、自定义工具和stdio MCP。测试还验证越界模型/权限修改、错误参数不会进入普通评分，并通过原编辑管线生成非提示词组件候选；原晋升与配对确认算法不变。

待内网完成：真实 HTTP/trace 映射与回执、隔离业务数据/工具可达性、公司模型凭据及配额、Linux 沙箱策略和进程托管。按 [INTRANET.zh-CN.md](INTRANET.zh-CN.md) 先冒烟，再把 profile 改为 ready 后启动。
