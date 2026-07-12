一、总体定位
当前项目是一个基于 FastAPI、MongoEngine、MongoDB 和 Docker Compose 的 AI 代码审核后端。核心参考 Alibaba OCR，但将 Git 分支审核改造成“本地两个版本目录对比”，并围绕既有 TaskModel、CodeFileModel、CodeBlock、Issue 数据结构扩展。
总体链路：
任务创建/调度
  -> 解析全量或增量目录
  -> 文件筛选与 diff
  -> 文件分批、预算与 resume
  -> plan_task
  -> main_task function calling
  -> 证据定位
  -> SARIF 静态分析佐证
  -> review_filter 反证过滤
  -> 文件内/批次去重
  -> 项目总结
  -> MongoDB 落库
二、工程分层
[main.py](C:/Users/qiao/Documents/ci-ai-codereview/app/main.py)：FastAPI 生命周期、数据库连接、调度器启停、路由注册。
[config.py](C:/Users/qiao/Documents/ci-ai-codereview/app/core/config.py)：通过环境变量管理数据库、LLM、并发、工具轮数、上下文、规则、SARIF、预算等配置。
[routes](C:/Users/qiao/Documents/ci-ai-codereview/app/routes)：HTTP 参数与响应转换，不承载审核逻辑。
[review_service.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/review_service.py)：主编排器，负责整个审核生命周期。
[diff_service.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/diff_service.py)：目录扫描、MD5 比较、rename、diff 和 CodeBlock 拆分。
[prompts.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/prompts.py)：所有阶段提示词和 function tools schema。
[review_tools.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/review_tools.py)：main_task 工具执行器。
[evidence.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/evidence.py)：代码证据匹配和行号定位。
[related_files.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/related_files.py)：确定性跨文件关系解析。
[static_analysis.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/static_analysis.py)：SARIF 静态分析结果加载与规范化。
[rules.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/rules.py)：OCR 风格 JSON 规则解析。
[llm_client.py](C:/Users/qiao/Documents/ci-ai-codereview/app/services/llm_client.py)：OpenAI-compatible /chat/completions 调用。
三、任务入口
支持三种启动方式：
POST /tasks 创建任务，再通过 POST /tasks/{id}/review 同步执行。
POST /tasks/mock 创建配置指定的 mock 任务。
启用 APP_ENABLE_SCHEDULER=true 后，由 AsyncIOScheduler 周期性创建并异步执行 mock 任务。
当前 scheduler 仍是演示实现：它不会扫描数据库中所有 state=0 的任务，而是每次创建一条 mock Task，再通过 asyncio.to_thread 执行审核。
任务状态：
state=0：等待审核。
state=1：已开始。
state=2：全部目标文件审核完成。
state=3：部分完成、预算跳过、main_task 未闭环或任务失败。
四、任务类型与路径
task_type=1 表示增量审核，task_type=2 表示全量审核。未明确指定时：
copy_from_version 为 ""、0 或 0_version：全量审核。
其他值：增量审核。
路径由 CODE_REPOSITORY_ROOT/project_id/version 组成，也可以通过 TaskModel.parent_path 覆盖根路径。
五、增量审核
增量任务会解析 base 和 head 两个目录：
base = project_id/copy_from_version
head = project_id/review_version
处理过程：
按允许扩展名扫描目录，排除 .git、.venv、node_modules、.opencodereview 等目录。
对同路径文件计算 MD5；完全一致则跳过。
对仅存在于一侧的文件识别新增、删除。
对唯一且 MD5 相同的旧/新路径识别纯 rename，避免重复审核。
删除文件进入变更清单和 DiffMap，但不创建审核子任务。
使用 difflib.SequenceMatcher 生成带上下文的增量 diff。
每行格式固定为：
前6位行号 + 第7位标记(+/-/空格) + 2个空格 + 代码
六、全量审核
全量任务读取目标目录所有允许文件，每一行都格式化为新增行。文件默认按语言分组，也可按目录分组，再依据 SCAN_BATCH_SIZE 切批。
FULL_SCAN_TOKEN_BUDGET 可限制总估算 token；超预算文件仍落库，但状态为 skipped_budget，Task 最终为部分完成。
七、CodeBlock 拆分
单文件 diff 估算不超过 DIFF_TOKEN_THRESHOLD=10000 时只生成一个 CodeBlock。超过阈值时按行切分为多个块，每个块独立执行 plan、main、定位和过滤。
八、规则与相关文件
规则优先读取项目内 .opencodereview/rule.json，也可用 REVIEW_RULES_PATH 指定。支持：
{"rules":[{"path":"src/**/*.{c,h}","rule":"审核规则"}]}
规则按声明顺序 first-match-wins；没有显式规则时，合并内置语言、扩展名和路径规则。
RelatedFileResolver 会确定性识别源文件/头文件、include/import、实现/测试、多语言资源以及 C 函数定义与调用关系。相关 diff 被注入 plan/main，选择结果和原因写入 CodeBlock.related_files。
九、plan_task
每个 CodeBlock 首先执行 plan_task，输入由五部分组成：
基础 System Prompt。
plan 阶段任务指令。
文件、语言、规则、变更清单、相关文件和 SARIF 上下文。
当前 diff 与目标文件完整代码。
JSON 输出格式强约束。
plan_task 输出：
comment
change_summary
risk_level
最多 10 个 checkpoints
logic_score
performance_score
security_score
readable_score
code_style_score
JSON 解析失败时会追加修复指令并重试，默认额外重试 2 次；每次请求、响应、token、耗时和错误都会落入 ModelRoundTrace。
十、main_task
main_task 接收完整文件、当前 CodeBlock diff、plan 结构化结论、规则、其他变更文件、相关文件和静态分析证据。
增量文件默认最多 30 轮，全量文件默认最多 60 轮，同时受单次 LLM timeout 和单文件总 timeout 限制。
每轮流程：
检查文件总时限和上下文硬限制。
根据 token 阈值决定是否压缩历史。
将当前完整 messages 和 tools 发送给模型。
把 assistant message 追加到 messages。
解析并执行全部 tool calls。
把每个工具结果作为 role=tool 消息追加。
再次发送完整 messages，直到显式完成。
模型连续多轮不调用工具且不输出合法 fallback JSON 时会终止。畸形工具参数会作为失败 tool result 返回模型修正，不会直接中断文件审核。
十一、main_task 工具
file_find：按名称或正则查找仓库文件。
file_read_diff：读取当前或其他变更文件 diff，支持批量路径。
code_search：支持文本、正则、文件模式和大小写设置的代码搜索。
read_file：读取仓库文件指定行范围，限制路径、扩展名、大小和最大行数。
code_comment：批量提交 Issue，校验类型、严重度、行号、existing_code 和 evidence。
task_done：显式结束，状态只能是 DONE 或 FAILED。
只读工具具有结果缓存；相同参数重复调用时直接返回缓存，并在 ToolCallTrace.cached 中记录。
十二、main_task 完成条件
优先要求 task_done(state="DONE")。兼容不支持 function calling 的网关时，也允许约束 JSON fallback。
达到最大轮数、上下文硬限制、文件超时、连续空轮限制或 task_done(FAILED) 时，CodeBlock 标记未完成并填写最终 failure_message。可恢复的工具错误只进入工具轨迹，不污染最终失败状态。
十三、上下文压缩
默认在最大上下文约 60% 时触发，80% 为硬限制。压缩后保留：
原始 system 和首轮完整 user 上下文。
已压缩的历史摘要。
最近若干完整 assistant/tool 轮次。
优先调用 LLM 生成历史摘要，失败时回退本地确定性摘要。压缩次数和调用轨迹均落库。
十四、Issue 后处理
main_task 生成 Issue 后依次执行：
本地证据定位：逐字连续匹配 existing_code，失败后才进行模糊匹配。
歧义控制：相同代码出现多次且原行号无法消歧时不猜位置。
RE_LOCATION_TASK：仅对本地无法定位的问题调用 LLM 重定位。
SARIF 佐证：匹配当前文件、变更行和问题语义。
本地有效性门禁：检查字段、行号、置信度和变更行重叠。
REVIEW_FILTER_TASK：只有 diff 存在直接反证时才允许过滤。
文件内去重：相同位置、类型、严重度和证据的问题合并。
被过滤或重复的问题不会删除，而是保存为 issue_show=false，保留审核和反馈依据。
十五、SARIF 静态证据
可通过 REVIEW_STATIC_ANALYSIS_SARIF_PATHS 加载 CodeQL、Semgrep、clang-tidy 等 SARIF 2.1.0 报告。
只接受仓库内部报告，并限制文件大小和 finding 数。只有与当前 CodeBlock 变更行重叠的 finding 会进入 prompt。
匹配成功后 Issue 写入：
static_corroborated
static_analysis_sources
static_analysis_rule_ids
static_analysis_fingerprints
原始结果存入 CodeBlock.static_findings，任务汇总存入 developer_issue_summary._static_analysis。
十六、并发、批次与恢复
文件审核使用 ThreadPoolExecutor，并发数由 LLM_CONCURRENCY 控制。批次完成后先做确定性去重，达到阈值时再执行 LLM 语义去重，并通过本地安全条件二次验证。
resume 同时校验：
source_hash：文件、diff 和完整代码是否变化。
review_fingerprint：流水线版本、模型、规则、证据阈值、相关文件、SARIF finding 等是否变化。
只有指纹完全一致且历史文件无失败时才复用，状态写为 extra.status=resumed。
十七、项目级收尾
所有文件结束后：
计算文件和任务五维平均分。
汇总可见 Issue 类型与严重度。
统计静态分析、预算、resume、跳过和不完整文件。
full scan 多文件任务生成项目摘要，失败时使用确定性统计摘要。
汇总 token、耗时和工具调用次数。
根据完整性设置 Task state=2 或 state=3。
十八、数据模型
TaskModel 保存项目级状态、五维评分、文件数量、预算、token、耗时、工具统计、项目摘要和任务级模型轨迹。
CodeFileModel 保存文件路径、任务类型、行数、五维评分、CodeBlock 列表以及 source hash、review fingerprint、相关文件和处理状态。
CodeBlock 保存 diff 行、plan 结果、main 完成模式、Issue、SARIF findings、token、耗时、模型轮次和工具轨迹。
Issue 保存描述、类型、1～5 严重度、建议、代码证据、定位结果、过滤结果、静态佐证、去重信息和反馈字段。
十九、可观测性
每轮模型请求保存输入摘要、输出摘要、模型、token、推理 token、缓存 token、耗时、finish reason、工具数量和错误。
每次工具调用保存参数、结果摘要、成功状态、缓存状态、耗时和错误。由此可以追踪“为什么漏审、为什么误报、模型看过哪些上下文、在哪一轮出现偏差”。
二十、接口与部署
主要接口为 /health、/tasks、/tasks/{id}/review、/code-files 和 /code-files/{id}。MongoDB 可使用真实实例或 mongomock；Docker Compose 提供 app 与 mongodb 服务、持久化 volume 和健康检查。当前完整测试为 42 passed。