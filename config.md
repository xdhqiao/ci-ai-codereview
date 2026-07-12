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
| `APP_ENABLE_SCHEDULER` | `false` | 是否启用 `AsyncIOScheduler`。生产使用外部任务系统时建议关闭。 |
| `SCHEDULER_INTERVAL_SECONDS` | `300` | mock scheduler 执行间隔。当前 scheduler 每次创建 mock Task，不扫描已有 `state=0` 任务。 |

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
| `DIFF_TOKEN_THRESHOLD` | `10000` | 单个 CodeBlock 的近似 token 上限，超过后按行拆块。建议 8000～12000。 |
| `DIFF_CONTEXT_LINES` | `10` | 每个变更周围保留的上下文行数。建议 8～15。 |
| `CODE_REPOSITORY_ROOT` | 空 | 本地代码仓库总根目录，例如 `D:/codereview`。生产必须明确设置或使用 Task `parent_path`。 |
| `REVIEW_EXCLUDE_DIRS` | 多个目录 | 逗号分隔的排除目录。建议排除依赖、构建产物、缓存和生成目录。 |
| `REVIEW_ALLOWED_EXTENSIONS` | 多语言扩展名集合 | 允许审核的扩展名；存在于代码默认值，但当前未写入 `.env.example` 和 Compose。 |

`DIFF_TOKEN_THRESHOLD` 太小会拆散逻辑单元，太大会造成 prompt 过长。当前 10000 是较稳妥的折中值。

## 7. 全量扫描与批次

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `SCAN_BATCH_SIZE` | `20` | 每个处理批次包含的文件数，不等于并发数。建议 10～30。 |
| `SCAN_BATCH_STRATEGY` | `by-language` | 支持 `by-language` 或 `by-directory`。多语言仓库推荐前者。 |
| `FULL_SCAN_TOKEN_BUDGET` | `0` | 全量扫描估算 token 预算；`0` 表示不限。成本敏感时设置明确上限。 |
| `FULL_SCAN_BATCH_DEDUP_ENABLED` | `true` | 启用批次问题去重。建议开启。 |
| `FULL_SCAN_BATCH_DEDUP_LLM_ENABLED` | `true` | 确定性去重后再使用 LLM 做语义分组。成本优先时可关闭。 |
| `FULL_SCAN_BATCH_DEDUP_MIN_COMMENTS` | `4` | 达到该问题数才调用 LLM 去重。建议 4～8。 |
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

这些值过大会增加 prompt 噪声和内存，过小则可能截断关键上下文。

## 13. mock 与调度测试

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `MOCK_PROJECT_ID` | `mock-project` | scheduler/mock 接口创建任务时使用的项目名。 |
| `MOCK_PARENT_PATH` | 空 | mock 代码根目录。 |
| `MOCK_COPY_FROM_VERSION` | 空 | mock 增量基线版本。 |
| `MOCK_REVIEW_VERSION` | `/app` | mock 审核版本或目录。 |
| `MOCK_TASK_TYPE` | `2` | `1` 表示增量，`2` 表示全量。 |

Compose 当前只透传 `MOCK_REVIEW_VERSION` 和 `MOCK_TASK_TYPE`。需要在容器内定制其余 mock 参数时，应补充 Compose environment。

## 14. Docker Compose 配置

- MongoDB 暴露 `27017`，数据保存到 `mongodb_data` volume。
- app 暴露 `8000`，等待 MongoDB healthcheck 成功后启动。
- MongoDB 每 10 秒检查一次，5 次失败后判定异常。
- app 每 15 秒访问 `/health`，5 次失败后判定异常。
- 两个服务均使用 `restart: unless-stopped`。
- 宿主已有 MongoDB 时建议将端口改为 `27018:27017`，避免连接目标歧义。

## 15. 推荐生产配置

```env
APP_ENV=prod
APP_ENABLE_SCHEDULER=false

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

## 16. 关键配置关系

1. `LLM_FILE_TIMEOUT_SECONDS` 应大于 `LLM_TIMEOUT_SECONDS`，推荐至少为其 2～3 倍。
2. `LLM_CONTEXT_HARD_RATIO` 必须大于 `LLM_CONTEXT_SOFT_RATIO`。
3. 真实审核必须同时满足 `LLM_MOCK_ENABLED=false` 且 `LLM_URL` 非空。
4. `LLM_MAX_CONTEXT_TOKENS` 不应高于模型真实上下文窗口。
5. `LLM_CONCURRENCY`、模型限流和数据库连接容量需要一起评估。
6. `FULL_SCAN_TOKEN_BUDGET=0` 表示不限制，不适合成本必须严格受控的环境。
7. 真实 API Key 不得写入 `.env.example`、Dockerfile、Compose 文件或提交到 Git。
