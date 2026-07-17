# 配置参数说明

本项目配置定义集中在 `app/core/config.py`，环境变量示例位于 `.env.example`。

配置优先级为：**进程环境变量 > `.env` > 代码默认值**。`get_settings()` 使用缓存，进程运行中修改 `.env` 后通常需要重启。

## 1. 应用配置

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `APP_NAME` | `ci-ai-codereview` | FastAPI 应用标题，只影响应用元数据。 |
| `APP_ENV` | `local` | 环境标识；当前不根据该值切换业务逻辑，可设为 `dev`、`test` 或 `prod`。 |
| `APP_HOST` | `0.0.0.0` | 监听地址。Dockerfile 当前直接使用 `0.0.0.0`，容器内只修改该值不会改变 uvicorn 参数。 |
| `APP_PORT` | `8000` | 应用端口。Dockerfile 和 Compose 当前固定为 8000。 |
| `APP_ENABLE_SCHEDULER` | `false`（Compose 默认 `true`） | 是否启用 server 端 `AsyncIOScheduler`。生产审核 server 应开启；仅 API/client 节点应关闭。 |
| `SCHEDULER_INTERVAL_SECONDS` | `5` | 待审任务扫描与运行中任务心跳间隔。建议 3～10 秒。 |
| `SCHEDULER_LEASE_SECONDS` | `120` | worker 任务租约时长。应明显大于扫描间隔；建议为扫描间隔的 10 倍以上。服务异常退出后，其他实例会在租约过期后恢复任务。 |
| `SCHEDULER_MAX_TASK_RETRIES` | `3` | partial/failed 任务自动重试上限。持续失败达到上限后保留状态与诊断数据，等待人工处理或再次触发。 |
| `SCHEDULER_RETRY_BACKOFF_SECONDS` | `30` | 自动重试的初始等待时间，单位秒。第 1、2、3 次失败后默认等待 30、60、120 秒，避免模型服务异常时连续请求。 |
| `SCHEDULER_RETRY_BACKOFF_MAX_SECONDS` | `900` | 自动重试退避上限，单位秒。建议 300～1800。人工点击续审不受该等待时间限制。 |

## 2. MongoDB 配置

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `MONGODB_URI` | `mongodb://mongodb:27017/ci_ai_codereview` | MongoDB 连接地址。容器内使用服务名 `mongodb`，宿主运行通常使用 `127.0.0.1`。 |
| `MONGODB_DB` | `ci_ai_codereview` | MongoEngine 使用的数据库名。测试、开发和生产应使用不同数据库。 |
| `MONGODB_ALIAS` | `default` | MongoEngine connection alias。当前未写入 `.env.example`，通常无需修改。 |
| `MONGO_MOCK` | `false` | 使用 mongomock 内存数据库。单元测试设为 `true`，真实运行必须为 `false`。 |

生产环境建议为 MongoDB 开启认证，不要把账号密码提交到仓库。宿主已有 MongoDB 时注意不要与 Compose 的 `27017:27017` 端口冲突。

## 3. LLM 基础配置

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `LLM_URL` | 空 | OpenAI-compatible 服务地址；代码会自动补 `/chat/completions`。为空时自动进入 mock。 |
| `LLM_API_KEY` | 空 | Bearer API Key。只通过进程环境变量或密钥服务注入。 |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名称，必须与服务端实际支持名称一致。 |
| `LLM_MOCK_ENABLED` | `true` | 启用本地确定性 mock。真实审核必须设为 `false`，并同时设置 `LLM_URL`。 |
| `LLM_TIMEOUT_SECONDS` | `120` | 单次 LLM API 超时。普通模型建议 120～180，慢推理模型建议 300。 |
| `LLM_FILE_TIMEOUT_SECONDS` | `600` | 单文件 main_task 总时间上限。建议至少为单次 timeout 的 2～3 倍，通常 600～900。 |
| `LLM_CONCURRENCY` | `4` | 同时审核的文件数。不是单文件内部轮次并发。建议从 2～4 起步。 |
| `LLM_JSON_RETRY_TIMES` | `2` | plan、重定位、过滤等 JSON 解析失败后的额外重试次数；总尝试数为 3。 |

`LLM_CONCURRENCY` 调大可以缩短墙钟时间，但会增加瞬时 QPS、token 吞吐和 429 风险。建议根据模型服务限流逐步提高。

## 4. main_task 循环

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `LLM_MAX_TOOL_ROUNDS` | `30` | 增量 CodeBlock main_task 最大 API 轮数，与 OCR diff review 一致。 |
| `FULL_SCAN_MAX_TOOL_ROUNDS` | `60` | 全量 CodeBlock main_task 最大轮数，与 OCR scan 一致。 |
| `LLM_MAX_CONSECUTIVE_EMPTY_ROUNDS` | `3` | 连续无有效工具结果或无合法 JSON 的终止阈值。建议保持 3。 |

轮数是上限，不是必跑次数。模型调用 `task_done` 后会立即结束。真实测试平均每文件约 6～7 轮，因此不建议简单统一降低到 10。

## 5. 上下文与压缩

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `LLM_MAX_CONTEXT_TOKENS` | `58888` | 用于估算的模型上下文上限，必须不高于模型真实输入窗口。 |
| `LLM_CONTEXT_SOFT_RATIO` | `0.60` | 上下文达到约 60% 时自动压缩。建议 0.55～0.65。 |
| `LLM_CONTEXT_HARD_RATIO` | `0.80` | 达到约 80% 且压缩后仍过大时终止。必须大于 soft。 |
| `LLM_CONTEXT_COMPRESS_TOKEN_THRESHOLD` | `0` | 显式压缩阈值；`0` 表示使用 `MAX_CONTEXT × SOFT_RATIO` 自动计算。 |
| `LLM_CONTEXT_COMPRESS_ROUNDS` | `4` | 每隔约 4 轮触发一次轮次型压缩；设为 `0` 只保留 token 触发。 |
| `LLM_CONTEXT_COMPRESSION_LLM_ENABLED` | `true` | 使用 LLM 总结历史；失败时回退本地确定性摘要。开启会增加额外 API。 |
| `LLM_CONTEXT_KEEP_RECENT_MESSAGES` | `6` | 压缩后保留的最近消息数量，至少按 2 处理。建议 6～10。 |
| `LLM_CONTEXT_SUMMARY_MAX_CHARS` | `2000` | 历史摘要最大字符数。大型复杂文件可设为 3000～5000。 |

压缩会保留最初的 system、完整 diff、完整文件和最近工具轮次。`LLM_MAX_CONTEXT_TOKENS` 配得高于模型真实窗口会导致 API 先报错，配得过低则会过早压缩。

## 6. diff 与 CodeBlock

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `DIFF_TOKEN_THRESHOLD` | `10000` | 单个 CodeBlock 的近似 token 上限，超过后按行拆块。C/C++ 项目建议 8000～12000；默认 10000。 |
| `DIFF_CONTEXT_LINES` | `10` | 每个变更周围保留的上下文行数。建议 8～15。 |
| `CODE_REPOSITORY_ROOT` | 空 | 本地代码仓库总根目录，例如 `D:/codereview`。生产必须明确设置或使用 Task `parent_path`。 |
| `REVIEW_EXCLUDE_DIRS` | 多个目录 | 逗号分隔的排除目录。建议排除依赖、构建产物、缓存和生成目录。 |
| `REVIEW_EXCLUDE_PATHS` | 业务默认列表 | 逗号分隔、大小写不敏感；相对文件路径包含任意元素即排除。会与 `ProjectModel.exclude_path` 合并，被排除文件不会进入 `CodeFileModel`。 |
| `REVIEW_ALLOWED_EXTENSIONS` | 多语言扩展名集合 | 允许审核的扩展名；存在于代码默认值，但当前未写入 `.env.example` 和 Compose。 |

`DIFF_TOKEN_THRESHOLD` 太小会拆散函数和数据流，太大会造成 prompt 过长。当前 10000 并不偏小：plan/main 除 Block 外还会携带完整目标文件、规则、Background、相关文件和工具历史。在 `LLM_MAX_CONTEXT_TOKENS=58888` 下建议保持 10000；函数普遍很长且模型窗口至少 64k 时可试 12000，不建议直接提高到 20000。修改方式是在 `.env` 或进程环境变量中设置，例如 `DIFF_TOKEN_THRESHOLD=12000`，然后重启服务；Compose 用户执行 `docker compose up -d --build` 使新环境生效。

该值是基于字符数的近似 token 预算，不是 tokenizer 的精确计数。小于阈值的单文件 diff/全量代码保持一个 Block；超过阈值才拆分。多行注释状态会跨拆分边界传递，纯注释 Block 不会因为恰好从 `/* ... */` 中间拆开而误触发 LLM。

## 7. 全量扫描与批次

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `SCAN_BATCH_SIZE` | `20` | 每个处理批次包含的文件数，不等于并发数。建议 10～30。 |
| `SCAN_BATCH_STRATEGY` | `by-language` | 支持 `by-language` 或 `by-directory`。多语言仓库推荐前者。 |
| `FULL_SCAN_TOKEN_BUDGET` | `0` | 全量扫描估算 token 预算；`0` 表示不限。成本敏感时设置明确上限。 |
| `FULL_SCAN_BATCH_DEDUP_ENABLED` | `true` | 启用批次问题分组。只写重复组元数据，不隐藏任何文件中的问题。 |
| `FULL_SCAN_BATCH_DEDUP_LLM_ENABLED` | `true` | 确定性分组后再使用 LLM 做语义分组。成本优先时可关闭。 |
| `FULL_SCAN_BATCH_DEDUP_MIN_COMMENTS` | `4` | 达到该问题数才调用 LLM 分组。建议 4～8。 |
| `FULL_SCAN_PROJECT_SUMMARY_ENABLED` | `true` | 启用项目级总结。建议开启。 |
| `FULL_SCAN_PROJECT_SUMMARY_LLM_ENABLED` | `true` | 使用 LLM 生成总结，失败时回退确定性摘要。 |
| `FULL_SCAN_PROJECT_SUMMARY_MAX_ISSUES` | `200` | 项目总结最多输入的问题数。建议 100～300。 |

`SCAN_BATCH_SIZE` 太大不会提高文件并发，却会让批次去重输入变大；真正控制并发的是 `LLM_CONCURRENCY`。

## 8. resume

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_RESUME_ENABLED` | `true` | 复用代码、模型、规则、证据配置等指纹完全一致的已完成文件。生产建议开启。 |

resume 同时校验 `source_hash` 和 `review_fingerprint`。模型、规则、相关文件、SARIF finding 或流水线版本改变时会重新审核。

## 9. 规则、定位与过滤

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_RULES_PATH` | 空 | 外部规则 JSON。为空时自动寻找 `<repo>/.opencodereview/rule.json`。 |
| `REVIEW_RELOCATION_ENABLED` | `true` | 启用本地定位及必要时的 LLM 重定位。建议始终开启。 |
| `REVIEW_FILTER_ENABLED` | `true` | 启用本地门禁和 REVIEW_FILTER_TASK。精确度优先必须开启。 |
| `REVIEW_FILTER_MIN_CONFIDENCE` | `0.45` | 低于该模型置信度的问题会被隐藏。高精确模式可设 0.55～0.65。 |
| `REVIEW_EVIDENCE_REQUIRED` | `true` | 要求 `existing_code` 作为可核验代码证据。建议始终开启。 |
| `REVIEW_LINE_EVIDENCE_MIN_SIMILARITY` | `0.55` | 模糊代码证据最低相似度。建议 0.55～0.70。 |
| `REVIEW_ALLOW_HEURISTIC_RELOCATION` | `false` | 没有 `existing_code` 时是否猜测行号。精确度优先应保持关闭。 |
| `REVIEW_CHANGE_MANIFEST_LIMIT` | `500` | prompt 中最多展示的其他变更文件数量。普通项目建议 200～500。 |

高精确模式推荐：过滤开启、证据必需、启发式定位关闭、相似度设置为 0.60～0.70。

## 10. 相关文件上下文

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_RELATED_FILES_ENABLED` | `true` | 启用源/头文件、调用关系、测试、资源族等相关文件解析。 |
| `REVIEW_RELATED_FILE_LIMIT` | `8` | 每个目标文件最多关联文件数。建议 5～10。 |
| `REVIEW_RELATED_DIFF_MAX_CHARS` | `12000` | 相关 diff 内联字符总预算。建议 8000～20000。 |

数量过大会把无关模块引入 prompt；当前 8 个文件和 12000 字符适合大多数项目。

## 11. SARIF 静态分析

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_STATIC_ANALYSIS_ENABLED` | `true` | 启用 SARIF 证据加载。无路径时不会产生 finding。 |
| `REVIEW_STATIC_ANALYSIS_SARIF_PATHS` | 空 | 仓库内 SARIF 路径或 glob，多个值逗号分隔，例如 `.opencodereview/*.sarif`。 |
| `REVIEW_STATIC_ANALYSIS_MAX_FINDINGS` | `2000` | 单任务最多加载的 finding 数。普通项目建议 500～2000。 |
| `REVIEW_STATIC_ANALYSIS_MAX_REPORT_BYTES` | `20971520` | 单报告最大 20 MiB。大型 CodeQL 报告可适当提高。 |

静态分析未报告某问题不会过滤 LLM Issue；只有位置和语义匹配时才增强置信度。生产建议接入 CodeQL、Semgrep 或 clang-tidy 的 SARIF。

## 12. 工具安全与结果上限

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_TOOL_MAX_READ_LINES` | `500` | `read_file` 单次最大读取行数。建议 300～800。 |
| `REVIEW_TOOL_MAX_SEARCH_MATCHES` | `100` | `code_search` 最大匹配数。建议 50～100。 |
| `REVIEW_TOOL_MAX_FILE_BYTES` | `2097152` | 工具允许读取的单文件上限，默认 2 MiB。 |
| `REVIEW_TOOL_TIMEOUT_SECONDS` | `10` | 本地搜索和读取的时间预算。大型仓库可设 15～30。 |
| `REVIEW_SEMANTIC_INDEX_ENABLED` | `true` | 启用任务级 Tree-sitter AST 语义索引和三个 main_task 语义工具。 |
| `REVIEW_SEMANTIC_INDEX_MAX_FILES` | `5000` | 单任务最多索引文件数。超大仓库应按模块拆分或提高该值。 |
| `REVIEW_SEMANTIC_INDEX_MAX_FILE_BYTES` | `2097152` | 进入语义索引的单文件大小上限，默认 2 MiB。 |
| `REVIEW_SEMANTIC_INDEX_MAX_RESULTS` | `100` | 三个语义工具单次最大结果数。 |
| `REVIEW_SEMANTIC_INDEX_BUILD_TIMEOUT_SECONDS` | `60` | 首次语义工具调用触发索引构建的总时间上限。 |

这些值过大会增加 prompt 噪声和内存，过小则可能截断关键上下文。

语义索引采用 Symbol、Reference、CallEdge 三类结构。C、C++、Python、JavaScript/TypeScript、Java、Go 使用 Tree-sitter；其他允许语言使用带明确 backend 标记的词法降级结果。索引是 lazy build，只有 main_task 首次调用语义工具时才构建。

## 13. Client、调度与断点恢复

`POST /tasks/trigger` 接收 `project_id`、`review_version`、`copy_from_version`、`review_version_path` 和 `copy_from_version_path`。`copy_from_version=0_version` 为全量审核，否则为增量审核。接口会同步完成目录扫描和 CodeFile/CodeBlock 预写，因此大型仓库 Jenkins HTTP 超时建议设为 600 秒以上。

重复的 `project_id + review_version + copy_from_version` 使用 `submission_key` 幂等归并，物理目录只表示本轮 Jenkins workspace 并更新到原 Task。Task 的 `trigger_count`、`trigger_revision` 增加，历史 token、调用次数和耗时不清零；每轮文件选择保存在 `ai_codereview_task_trigger`。Block 内容 MD5 相同且上次已完整审核时保留结果；MD5 变化时只重置对应 Block。审核阶段每完成一个 Block 就保存一次，进程中断后按 Block 的 `review_state`、`main_task_completed`、`block_hash` 和 `review_fingerprint` 决定复用或重跑。累计报告使用固定 URL；追加 `?trigger_revision=N` 只筛选第 N 轮变化的文件，但仍展示数据库中的最新 Block 代码与审核结果。

调度顺序为增量优先、同类 FIFO。运行中的全量任务发现待审增量任务后设置协作式停止信号；当前不可取消的 LLM HTTP 请求返回后，在下一检查点释放租约并恢复为待审。多 server 使用原子领取、lease token 和 heartbeat 防止正常情况下重复执行；异常退出后等待 lease 过期恢复。

Docker 内的代码工具读取 `CODE_REPOSITORY_CONTAINER_ROOT` 挂载目录，Jenkins 必须提交容器可见路径。该目录建议只读挂载，MongoDB volume 负责保存断点和结果。报告页只引用本服务的 `/static/report.css` 和 `/static/report.js`，不依赖互联网资源。

## 14. mock 参数

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `MOCK_PROJECT_ID` | `mock-project` | scheduler/mock 接口创建任务时使用的项目名。 |
| `MOCK_PARENT_PATH` | 空 | mock 代码根目录。 |
| `MOCK_COPY_FROM_VERSION` | 空 | mock 增量基线版本。 |
| `MOCK_REVIEW_VERSION` | `/app` | mock 审核版本或目录。 |
| `MOCK_TASK_TYPE` | `2` | `1` 表示增量，`2` 表示全量。 |

Compose 当前只透传 `MOCK_REVIEW_VERSION` 和 `MOCK_TASK_TYPE`。需要在容器内定制其余 mock 参数时，应补充 Compose environment。

## 15. Docker Compose 配置

- MongoDB 暴露 `27017`，数据保存到 `mongodb_data` volume。
- app 暴露 `8000`，等待 MongoDB healthcheck 成功后启动。
- 宿主代码目录由 `CODE_REPOSITORY_HOST_ROOT` 只读挂载到 `CODE_REPOSITORY_CONTAINER_ROOT`，默认分别为 `./demo_repos` 和 `/repositories`。
- MongoDB 每 10 秒检查一次，5 次失败后判定异常。
- app 每 15 秒访问 `/health`，5 次失败后判定异常。
- 两个服务均使用 `restart: unless-stopped`。
- 宿主已有 MongoDB 时建议将端口改为 `27018:27017`，避免连接目标歧义。

## 16. 推荐生产配置

```env
APP_ENV=prod
APP_ENABLE_SCHEDULER=true
SCHEDULER_INTERVAL_SECONDS=5
SCHEDULER_LEASE_SECONDS=120
SCHEDULER_MAX_TASK_RETRIES=3
SCHEDULER_RETRY_BACKOFF_SECONDS=30
SCHEDULER_RETRY_BACKOFF_MAX_SECONDS=900

MONGODB_URI=mongodb://user:password@mongodb:27017/ci_ai_codereview?authSource=admin
MONGODB_DB=ci_ai_codereview
MONGO_MOCK=false

LLM_URL=https://api.deepseek.com
LLM_API_KEY=${SECRET_FROM_RUNTIME}
LLM_MODEL=deepseek-v4-flash
LLM_MOCK_ENABLED=false
LLM_TIMEOUT_SECONDS=300
LLM_FILE_TIMEOUT_SECONDS=900
LLM_CONCURRENCY=4
LLM_MAX_TOOL_ROUNDS=30
FULL_SCAN_MAX_TOOL_ROUNDS=60

LLM_MAX_CONTEXT_TOKENS=58888
LLM_CONTEXT_SOFT_RATIO=0.60
LLM_CONTEXT_HARD_RATIO=0.80
LLM_CONTEXT_COMPRESSION_LLM_ENABLED=true

DIFF_TOKEN_THRESHOLD=10000
DIFF_CONTEXT_LINES=10
SCAN_BATCH_SIZE=20
SCAN_BATCH_STRATEGY=by-language

REVIEW_RESUME_ENABLED=true
REVIEW_EXCLUDE_PATHS=MCAL,Math,General,COMM,CANVector,main.c,Wdg,Smu,SafeTlib,SafeTpack,ERU_BSW,Eth_generated,Dem,DemConfig,FiM,FiMConfig,VStdLib,Etpu,freertos,FW_LIB,StartUp,Os_Stubs.c,Os_TaskInfr.c,.vscode,.history,**pycache**,BootloaderPlus_CData.c,PrjVer.c,PrjVer.h,SoftVer_Release.h
REVIEW_RELOCATION_ENABLED=true
REVIEW_FILTER_ENABLED=true
REVIEW_EVIDENCE_REQUIRED=true
REVIEW_ALLOW_HEURISTIC_RELOCATION=false
REVIEW_LINE_EVIDENCE_MIN_SIMILARITY=0.60

REVIEW_RELATED_FILES_ENABLED=true
REVIEW_RELATED_FILE_LIMIT=8
REVIEW_STATIC_ANALYSIS_ENABLED=true
REVIEW_STATIC_ANALYSIS_SARIF_PATHS=.opencodereview/*.sarif
```

## 17. 关键配置关系

1. `LLM_FILE_TIMEOUT_SECONDS` 应大于 `LLM_TIMEOUT_SECONDS`，推荐至少为其 2～3 倍。
2. `LLM_CONTEXT_HARD_RATIO` 必须大于 `LLM_CONTEXT_SOFT_RATIO`。
3. 真实审核必须同时满足 `LLM_MOCK_ENABLED=false` 且 `LLM_URL` 非空。
4. `LLM_MAX_CONTEXT_TOKENS` 不应高于模型真实上下文窗口。
5. `LLM_CONCURRENCY`、模型限流和数据库连接容量需要一起评估。
6. `FULL_SCAN_TOKEN_BUDGET=0` 表示不限制，不适合成本必须严格受控的环境。
7. 真实 API Key 不得写入 `.env.example`、Dockerfile、Compose 文件或提交到 Git。
8. `SCHEDULER_LEASE_SECONDS` 应远大于 `SCHEDULER_INTERVAL_SECONDS`，否则长 GC 或事件循环阻塞可能造成不必要的任务接管。
9. Jenkins 提交的物理路径必须对 server 可见；容器部署时通常应提交 `/repositories/...`，而不是 Jenkins 宿主机的盘符路径。
