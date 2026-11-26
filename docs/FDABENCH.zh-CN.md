# FDABench-Lite 报告实验（Linux，无 Docker）

当前 `rsi-platform` 已加入内置 `fdabench` 适配器，使用 OpenCode **1.18.32 原生 CLI** 执行。复用现有的发现 → 分析 → 生成候选 → 配对 TRAIN 评测 → 归因与确认 → 保留或回退 → 独立 TEST 流程。HTTP/Python 业务问答适配器仍独立存在；本报告 benchmark 的数据库、文档工具由平台提供，不会自动转接到公司的问答服务。

## 数据范围与评分

- 上游 117 道 report 题中，105 道发布了参考报告和 rubric。本次固定使用 **70 TRAIN / 35 TEST**；另 12 道不进入有监督评测。
- 划分保存在 `configs/fdabench_split.json`，种子 42；这是当前全量可评分版本，不是此前 40 TRAIN / 20 TEST 的 60 题子集。
- 16 个 SQLite 数据库、完整 1418 份 PDF，原始资料约 7.4 GB。另留出索引、下载临时文件和实验记录空间；建议至少 30 GB 空闲磁盘。
- SQL 只读，单次查询最多 1000 行、20 秒。文档使用全量 PDF 的逐页 FTS5/BM25 检索及按页阅读；不使用参考答案提供的命中文档来缩小资料池。
- 网页搜索使用已有的智谱 `web_search_prime` MCP，每次 solver 执行最多 15 次。需要服务器配置 `ZHIPU_API_KEY`。
- 评分器在平台侧调用模型，分别评 SQL 准确性、外部资料整合、逻辑推理、完整性，再按题目 rubric 权重汇总为 `[0,1]` 连续 RS。默认复用分析模型，也能独立配置 judge。
- **优化目标为 `mean_reward`（平均 RS）**。`pass_at_1` 继续表示满分回答比例，不会把“部分分提高”误算成零提升。保留候选仍需配对证据、行为归因和确认，均分提高本身不能绕过这些条件。

预算里的 creation 是逻辑试验次数，不是 API 调用次数或金额；每次试验有多步执行和 4 个评分维度，分析与失败重试也会产生额外模型费用。

这是当前工具环境与可配置模型下的 **adapted RS**，不能直接当作官方排行榜分数。文档检索为词法检索，不是官方 embedding/FAISS；网页搜索有时效变化，应保留每轮工具结果。

## 1. 安装并填写配置

在服务器 checkout 根目录执行：

```bash
git pull --ff-only
bash scripts/setup_linux.sh
# Debian / Ubuntu；其他发行版安装对应的软件包即可。
sudo apt-get install -y bubblewrap poppler-utils
```

Python 依赖由 `uv.lock` 管理。FDABench 本身不新增 Python 第三方依赖；PDF 提取和进程隔离依赖系统的 `pdftotext`、`bwrap`。Linux 必须允许当前用户创建所需命名空间；`doctor` 会实际验证，失败时应由服务器管理员调整权限。

完整 PDF 源 `FDAbench2026/FDABench-File` 需要 Hugging Face 账户访问权限。下载前取得访问权限，并在服务器 `.env` 中设置现有的 `HF_TOKEN`；脚本不会自动接受数据集条款。

编辑私有 `.env`（不要提交到 Git），至少设置：

```dotenv
HAI_EXECUTION_BASE_URL=https://your-execution-provider.example/v1
HAI_EXECUTION_API_KEY=...
HAI_ANALYSIS_BASE_URL=https://your-analysis-provider.example/v1
HAI_ANALYSIS_API_KEY=...
ZHIPU_API_KEY=...
HAI_FDABENCH_ROOT=/data/fdabench-lite-report
HAI_FDABENCH_INDEX=/data/fdabench-index/documents.sqlite
HF_TOKEN=...
```

`HF_TOKEN` 只供下载器使用，需要你已有 FDABench-File 数据集访问权限；403 时先在 Hugging Face 申请访问，下载器不会自动同意协议。也支持在 shell 中 export 这些变量。

编辑 `configs/experiments/fdabench.toml` 的两个模型 ID 与 API 类型（`responses` / `chat_completions`）。模板中的 `your-*` 必须替换；两个模型可不同。模板默认开放 16 个通道，不强迫算法同时修改它们；不设置 `initial_harness` 即从空 Harness 开始。默认 8 并发、800 次 TRAIN 创建预算，可按服务器和模型额度调整。初始 TRAIN 为 70×2=140 次 solver 执行，后续配对筛选、确认继续消耗预算；每份报告的四维评分还会产生评测模型请求。

可选：评分模型与分析模型分开时，在 `.env` **同时**设置 `HAI_JUDGE_MODEL`、`HAI_JUDGE_BASE_URL`、`HAI_JUDGE_API`、`HAI_JUDGE_API_KEY`；否则四项都不设置。不要只设置其中一项。

## 2. 下载并准备数据

```bash
uv run python scripts/prepare_fdabench.py download --workers 6
uv run python scripts/prepare_fdabench.py prepare --workers 4
```

第一条下载固定版本任务、数据库和完整文档，按内容摘要验证。重复执行会校验并跳过完整文件；失败的文件重新下载，不保留部分文件为完成状态。支持 `--section tasks`、`--section databases`、`--section documents` 分步下载。部分数据库从 ZIP 通过 HTTP Range 按需读取，无需解压整个大归档。

第二条核验所有文件及任务／参考答案投影，再构建完整文档索引。首次构建耗时取决于服务器和 PDF 提取速度。索引带独占锁与输入摘要；输入改变时需使用新的索引目录，避免混用旧环境。

如需临时指定路径，各命令均支持 `--data-root /data/... --index-cache /data/...`。实际任务和界面读取 `.env` 中的路径，因此常规部署建议把路径固定在 `.env`。

```text
/data/fdabench-lite-report/
  tasks/tasks.jsonl                 # solver / explorer 可见的公开问题
  evaluation/references.jsonl       # 平台评分器专用，含 GT/rubric
  databases/*.sqlite
  documents/<category>/*.pdf
  metadata/                        # 来源列表、摘要与核验回执
/data/fdabench-index/
  documents.sqlite
  index.json
```

不需要把数据复制到 GitHub；仓库仅包含下载清单、摘要和划分。已经有旧版完整数据包时，可设置 `HAI_FDABENCH_ROOT` 指向它，跳过下载后直接 `prepare`。

## 3. 预检、单题试跑、正式实验

```bash
# 检查资产、模型配置、OpenCode 版本、真实 Linux 隔离和本地工具网络桥。
# 不访问模型、不计模型费用。
uv run python scripts/prepare_fdabench.py doctor

# 仅一条 TRAIN，真实调用执行模型与评分模型；先确认这条能完成。
uv run python scripts/prepare_fdabench.py smoke

# 自动生成 run ID，执行 TRAIN 自进化，并按 profile 做独立 TEST。
uv run python scripts/prepare_fdabench.py run
```

`smoke` 和 `run` 会产生真实模型调用。`doctor` 不保证远端模型服务可用；单题试跑负责验证这一层。

也可在原有 API / Worker 的实验控制台中新建实验，选择 `fdabench.toml`（Benchmark 为 FDABench Lite），集中选择执行／分析模型、允许通道、并发与进化参数后开始。界面和 CLI 共用适配器及文件记录；服务器前端的安装、构建、启动仍按 [内网部署说明](INTRANET.zh-CN.md) 执行。

## 记录、恢复和隔离

- 真实 provider 请求／响应 trace、原生组件回调、回答和工具日志均留在平台服务器的 `runs/` 中。工具服务按每个 trial 的 token 绑定数据库和网页搜索配额。
- 每个 solver 有独立文件工作区、隔离进程组和网络命名空间。只桥接该 trial 所需的模型代理和工具端口；平台凭据、参考报告不挂入 solver。
- API 请求沿用通用并发额度、超时、有限重试和退避。原生执行默认最多 2 次尝试（`HAI_NATIVE_EXECUTION_ATTEMPTS=1..3`），失败现场单独保留。评分失败不记为零分；已完成的 solver 回答和已评维度有检查点，重试只补未完成评分。
- 完成的 trial 在配置、输入、trace 摘要一致时可复用。中断而未完成的执行保留现场；受限重试使用新的 attempt 工作区。超出上限或配置发生变化时需检查故障并创建新实验，不能把坏样本当成正常失败。
- `full_evaluation=true` 会在 TRAIN 后评测初始版本和最终选择版本；若最终仍为初始版本，复用初始 TEST 结果。

仓库在开发机只做合成数据回归及静态检查。完整数据下载、Linux 原生端到端验证与大规模实验应在服务器完成。

## HTTPS 加密运行包

服务器无法从原数据源下载时，可使用 [加密运行包](https://github.com/gongye19/rsi-platform/releases/tag/fdabench-runtime-2026-11-26)。下载密钥单独交付，不包含在 Git 仓库和 Release 中。

```bash
git pull --ff-only
curl -fL https://github.com/gongye19/rsi-platform/releases/download/fdabench-runtime-2026-11-26/download.sh -o /tmp/download-fdabench.sh
bash /tmp/download-fdabench.sh /data/fdabench-lite-report
```

脚本支持断点续传，检查每个分卷的 SHA256，并在 GPG 完成完整性校验后才解压；运行时按提示粘贴单独提供的解密密钥。Linux 需安装 `curl`、`gnupg`。目标应为空目录。

运行包包含 16 个数据库、117 道公开问题与宿主侧评分资料，以及覆盖全部 1,418 份 PDF 的预处理文本索引（76,720 个文本块）。**不包含原始 PDF**；`document_search` 和 `document_read` 使用索引，与原执行工具一致。原始 PDF 仍可按前文从源站下载。

将 `.env` 的 `HAI_FDABENCH_ROOT` 设置为解压目录，照常执行 `prepare` 和 `doctor`。`prepare` 自动识别 `prebuilt/documents.sqlite`，校验仓库固定的索引摘要、文档覆盖数、数据库摘要和题目／参考投影后导入，不需要重新解析 PDF，也不需要 Hugging Face 凭据。执行和分析模型、实时网页搜索仍需独立配置。
