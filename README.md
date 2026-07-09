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
- `POST /tasks/{task_id}/review`：执行审核流程。任务开始时 `state=1`，所有文件审核完成后 `state=2`。
- `GET /code-files`、`GET /code-files/{code_file_id}`：查询落库后的文件审核结果。

## 增量扫描说明

增量任务直接对比 `copy_from_version` 和 `review_version` 指向的两个本地目录。若任务只保存版本名，服务会按 `parent_path/version`、`CODE_REPOSITORY_ROOT/project_id/version`、版本名本身的顺序解析路径。`copy_from_version=0_version`、`0` 或空字符串会按全量扫描处理。

若两边同名文件 MD5 不同，或目标目录新增文件，则生成自定义 diff：

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
LLM_MOCK_ENABLED=false
```

`main_task` 暴露的工具包括 `code_search`、`read_file`、`file_read`、`code_comment` 和 `task_done`。`code_comment` 保存的 `severity` 是 1 到 5 的整数，5 表示最严重。
