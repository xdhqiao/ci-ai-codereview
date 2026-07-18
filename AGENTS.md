# AGENTS.md

## 项目背景

这是一个基于 Python 的后端工程，主要技术栈包括 FastAPI、MongoDB、Docker、Docker Compose。项目目标是构建可维护、可测试、可本地部署的服务端系统。
项目的目的是参考 https://github.com/alibaba/open-code-review 的核心实现，比如代码审核第一步 plan_task，第二部是main_task，最后合并相同的审核问题列表。最终把数据存放到MongoDB的数据库中，如果时增量代码扫描，只支持本地两个文件夹的所有的代码对比扫描（类比于 ocr review --from main --to feature-branch的两个代码分支），如果是全量代码扫描，实现方式和 ocr scan 类似 

## 通用要求

* 使用 Python 3.12。
* Web 框架使用 FastAPI。
* MongoDB 使用MongoEngine 同步调用。
* 所有配置必须通过环境变量读取，不允许在代码中硬编码数据库地址、账号、密码。
* 必须提供 `.env.example`。
* 必须提供 `Dockerfile` 和 `docker-compose.yml`。
* 必须提供 `/health` 健康检查接口。
* 必须提供基本测试用例。
* 必须保证 `docker compose up --build` 后项目可以启动。
* README 必须包含启动方式、测试方式、主要接口说明和目录结构说明。

## 代码风格

* 使用清晰的分层结构：routes（api层）、service（所有的后台逻辑实现）、model(数据表定义)、tests等
* 路由层只负责 HTTP 入参和出参，不直接写复杂业务逻辑。
* Service 层负责业务逻辑。
* Pydantic 模型用于请求和响应数据校验。
* 函数和类命名必须清晰，不使用含糊缩写。
* 异常处理必须统一，不要在接口中随意返回字符串错误。

## Docker 要求

* Dockerfile 应尽量简洁。
* docker-compose.yml 至少包含 app 和 mongodb 两个服务。
* MongoDB 数据需要挂载 volume。
* app 服务需要依赖 mongodb。
* 提供合理的 healthcheck。
* 不要把 `.env`、数据库文件、缓存目录提交到 Git。
* env 包含但不限于 LLM URL，Key，模型，以及调用大模型的并发数
## 测试要求

* 使用 pytest。
* 至少覆盖健康检查接口、核心 CRUD 接口、数据库连接逻辑。
* 如果某些测试依赖 MongoDB，请在 README 中说明如何运行。
* 修改完成后必须尝试运行测试，并在最终回复中说明执行结果。

## Codex 工作方式

每次开始任务前，请先阅读当前仓库结构，再给出简短实现计划。
实现时优先保持小步提交思路，避免一次性重写无关文件。
完成后请总结修改了哪些文件、如何运行、如何测试、是否存在未完成事项。
