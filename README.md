# ci-ai-codereview

基于 FastAPI、MongoEngine 和 Docker Compose 的代码审核后端。实现参考 Alibaba open-code-review 的两阶段流程：先执行 `plan_task` 做代码块预评估，再执行 `main_task` 通过工具调用生成结构化问题，最后将任务、文件、代码块、评分和 issue 保存到 MongoDB。

## 目录结构

```text
app/
  core/        配置、MongoDB 连接、统一异常
  models/      MongoEngine 数据表定义
  routes/      HTTP 接口层
  schemas/     Pydantic 请求和响应模型
  services/    扫描、diff、prompt、LLM、工具调用和调度逻辑
tests/         pytest 测试
```

## 启动方式

```bash
cp .env.example .env
docker compose up --build
```

没有真实 LLM 配置时，默认 `LLM_MOCK_ENABLED=true`，服务会使用本地确定性规则完成 plan/main 两阶段，便于本地启动和测试。

## 测试方式

```bash
pytest
```

测试使用 `MONGO_MOCK=true`，不依赖本地 MongoDB。若要使用真实 MongoDB，可配置 `.env` 中的 `MONGODB_URI` 后再运行服务。

## 主要接口

- `GET /health`：健康检查，同时 ping MongoDB。
- `POST /tasks`：创建审核任务。`task_type=1` 表示本地两个目录的增量扫描，`task_type=2` 表示全量扫描。
- `GET /tasks`、`GET /tasks/{task_id}`、`DELETE /tasks/{task_id}`：任务 CRUD。
- `POST /tasks/mock`：按环境变量创建一个 mock 任务。
- `POST /tasks/{task_id}/review`：执行审核流程。任务开始时 `state=1`，所有文件审核完成后 `state=2`；存在预算跳过或 main_task 未闭环的文件时为 `state=3`、`completion_status=partial`。
- `GET /code-files`、`GET /code-files/{code_file_id}`：查询落库后的文件审核结果。

## 增量扫描说明

增量任务直接对比 `copy_from_version` 和 `review_version` 指向的两个本地目录。若任务只保存版本名，服务会按 `parent_path/version`、`CODE_REPOSITORY_ROOT/project_id/version`、版本名本身的顺序解析路径。`copy_from_version=0_version`、`0` 或空字符串会按全量扫描处理。

若两边同名文件 MD5 不同，或目标目录新增/删除文件，则生成自定义 diff。删除文件不单独启动审核，但会进入变更清单和只读 DiffMap，供其他目标文件通过 `file_read_diff` 核验跨文件影响：

```text
     1   unchanged context
     2-  old line
     2+  new line
```

格式为 6 位行号、第 7 位变更标记、后续两个空格和代码内容。每个变更默认保留 10 行上下文。若单文件 diff 估算小于 `DIFF_TOKEN_THRESHOLD=10000`，该文件只生成一个 `CodeBlock`；超过阈值时按行拆块。

## LLM 配置

`.env` 中可配置 OpenAI 兼容接口：

```bash
LLM_URL=https://example.com/v1
LLM_API_KEY=your-key
LLM_MODEL=gpt-4o-mini
LLM_CONCURRENCY=4
LLM_MAX_TOOL_ROUNDS=30
FULL_SCAN_MAX_TOOL_ROUNDS=60
LLM_FILE_TIMEOUT_SECONDS=600
LLM_CONTEXT_COMPRESS_ROUNDS=4
LLM_CONTEXT_COMPRESS_TOKEN_THRESHOLD=0
LLM_MAX_CONTEXT_TOKENS=58888
FULL_SCAN_TOKEN_BUDGET=0
REVIEW_RESUME_ENABLED=true
LLM_MOCK_ENABLED=false
```

`main_task` 暴露 `file_find`、`file_read_diff`、`code_search`、`read_file`、`code_comment` 和 `task_done`。`file_read_diff` 可批量读取任意变更文件；`code_search` 支持文件模式、大小写和正则；`code_comment` 支持在一次调用中批量提交问题。`severity` 是 1 到 5 的整数，5 表示最严重。

main_task 必须调用 `task_done(state="DONE")` 才算工具闭环完成；兼容网关不支持 function calling 时，可用约束 JSON fallback。畸形工具参数会作为 tool result 返回给模型继续修正，不会中断整个文件。增量审核默认最多 30 轮，full scan 默认 60 轮，同时受单文件总时限约束。

`LLM_CONCURRENCY` 会用于文件级并发审核，`SCAN_BATCH_SIZE` 控制每批文件数；full scan 默认按 `SCAN_BATCH_STRATEGY=by-language` 分组后切批，也可配置 `by-directory`。`LLM_CONTEXT_COMPRESS_TOKEN_THRESHOLD=0` 时按最大上下文的 60% 自动触发，80% 为硬阈值；压缩采用“初始 system/user 冻结区 + 历史摘要区 + 最近完整工具轮次活动区”，不会丢失原始 diff/完整文件。历史摘要默认由 LLM 提炼已确认问题、工具结论和待办，失败时回退本地确定性摘要，调用轨迹保存到 `model_rounds`。

全量扫描支持更接近 OCR scan 的项目级控制：

- `FULL_SCAN_TOKEN_BUDGET`：全量扫描估算 token 预算，`0` 表示不限制。超出预算的文件会落库为 `extra.status=skipped_budget`。
- `FULL_SCAN_BATCH_DEDUP_ENABLED`：先做确定性精确去重；达到 `FULL_SCAN_BATCH_DEDUP_MIN_COMMENTS` 后可再做 LLM 语义分组。语义分组必须完整覆盖输入，并通过类型、严重度、规则/证据相似度的本地二次校验，重复项保留但 `issue_show=false`。
- `FULL_SCAN_PROJECT_SUMMARY_ENABLED`：多文件任务结束时基于最终可展示 issue 生成 LLM 项目摘要，失败回退为确定性统计摘要，写入 `TaskModel.project_summary` 和 `developer_issue_summary._project_summary`。
- `REVIEW_RESUME_ENABLED`：重复执行同一 task 时，同时校验代码 `source_hash` 和审核 `review_fingerprint`。后者包含流水线版本、模型、规则和证据/过滤阈值；任一审核条件变化都会重跑，只有完全一致且历史无失败时才标记为 `extra.status=resumed`。

## 规则与准确度增强

规则上下文由 `app/services/review_rules.json` 解析生成，也可以通过 `REVIEW_RULES_PATH` 指向外部 JSON。除原有语言/路径格式外，还兼容 OCR 的 `{"rules":[{"path":"src/*.{c,h}","rule":"..."}]}` 格式；该格式按声明顺序 first-match-wins，避免多个规则叠加造成提示噪声。解析结果会进入 plan_task、main_task、RE_LOCATION_TASK 和 REVIEW_FILTER_TASK。

plan_task 和 main_task 还会接收确定性的相关文件上下文。`RelatedFileResolver` 按源文件/头文件配对、显式 include/import、实现/测试命名、多语言资源族以及 C 函数定义与调用关系筛选候选文件，仅内联受预算限制的相关 diff。选择结果和原因写入 `CodeBlock.related_files` 与 `CodeFileModel.extra.related_files`，便于解释模型为什么读取或遗漏某个跨文件契约。可通过以下配置控制：

- `REVIEW_RELATED_FILES_ENABLED`：是否启用相关文件解析，默认启用。
- `REVIEW_RELATED_FILE_LIMIT`：每个目标文件最多关联的文件数，默认 8。
- `REVIEW_RELATED_DIFF_MAX_CHARS`：相关 diff 的总内联字符预算，默认 12000；超出部分仍可由 `file_read_diff` 按需读取。

可通过 SARIF 2.1.0 接入 CodeQL、Semgrep、clang-tidy 或其他静态分析器的独立证据：

- `REVIEW_STATIC_ANALYSIS_SARIF_PATHS`：仓库内 SARIF 路径或逗号分隔的 glob，例如 `.opencodereview/*.sarif`。
- `REVIEW_STATIC_ANALYSIS_MAX_FINDINGS`：单任务最多加载的 finding 数，默认 2000。
- `REVIEW_STATIC_ANALYSIS_MAX_REPORT_BYTES`：单报告大小上限，默认 20 MiB。

系统只把当前文件且与新增/修改行重叠的 finding 注入 plan/main。经过行号和语义匹配后，Issue 会写入 `static_corroborated`、`static_analysis_sources`、`static_analysis_rule_ids` 和稳定指纹；原始 finding 保存在 `CodeBlock.static_findings`。静态工具未报告某问题不构成反证，因此不会据此隐藏 LLM Issue。任务级汇总位于 `developer_issue_summary._static_analysis`。

`plan_task` 除五维评分和整体评论外，还输出 `change_summary`、`risk_level`、最多 10 个结构化 `checkpoints` 及建议工具调用，并保存到 `CodeBlock.plan_*` 字段。main_task 会逐项核验这些检查点，同时独立扫描遗漏风险。

main_task 之后会继续执行两个准确度增强阶段：

- 确定性证据定位：先对 `existing_code` 做多行连续匹配、重复次数统计、原行号消歧和变更行重叠校验；只有失败项才进入 `RE_LOCATION_TASK`，模型返回的新片段还会再次经过确定性验证。
- `REVIEW_FILTER_TASK`：本地先过滤缺字段、低置信度、错行和证据不匹配问题；LLM 只充当反证事实核查器，只有 diff 存在直接反证时才能过滤，无法验证但不能证伪的问题必须保留。

`code_comment` 要求模型同时提供 `existing_code` 和 `evidence`。定位结果会写入 `evidence_match_status`、`evidence_match_score`、起止行、匹配次数、来源、歧义状态和位置置信度。`REVIEW_EVIDENCE_REQUIRED` 与 `REVIEW_LINE_EVIDENCE_MIN_SIMILARITY` 可控制证据门禁强度；启发式猜行默认关闭。

## 审核可观测数据

每个 `CodeBlock` 会保存本次审核的诊断轨迹，方便解释漏审、误报和提示词效果：

- `model_rounds`：每一轮 `plan_task` / `main_task` 的模型调用摘要、输出摘要、模型名、finish reason、token usage 和耗时。
- `tool_calls`：每次 function calling 的工具名、参数、结果摘要、成功状态和耗时。
- `main_task_completed`、`main_task_completion_mode`、`main_task_round_count`：区分显式 `task_done`、JSON fallback、轮次耗尽、上下文超限和超时。
- `memory_compression_count`：main_task 工具循环中发生上下文压缩的次数。
- `Issue.existing_code`、`Issue.evidence`、`Issue.evidence_match_status`、`Issue.evidence_match_score`：问题证据与本次变更代码的匹配情况。
- `TaskModel.project_summary`：任务级审核摘要，包括主要问题类型、严重度分布、重点文件和覆盖缺口。
- `TaskModel.task_model_rounds`：批次语义去重和项目摘要的任务级模型输入输出摘要、token 与耗时。
- `TaskModel.llm_*`、`tool_call_summary`：跨全部代码块和任务级调用的实际 token、耗时与工具次数汇总。
- `CodeFileModel.extra.status`：文件处理状态，常见值为 `reviewed`、`resumed`、`partial`、`skipped_budget`。
- `llm_prompt_tokens`、`llm_completion_tokens`、`llm_total_tokens`：当前代码块累计 token。
- `llm_reasoning_tokens`、`llm_cached_tokens`：模型返回的推理 token 和缓存 token，接口不返回时为 0。
- `llm_elapsed_ms`、`process_time`：模型累计耗时和代码块总处理耗时。
- `failure_message`：模型调用失败、JSON 重试失败或工具异常等可诊断信息。
