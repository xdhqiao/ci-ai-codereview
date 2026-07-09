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

## 实现大纲
我们把 https://github.com/alibaba/open-code-review 命名为 ocr，由于 ocr 使用golang 实现，该项目是参照golang并结合已有的业务代码的定义共同完成。
### 1.  通过syncIOScheduler异步扫描需要审核的task，这里可以mock出来一个task数据，不需要写逻辑，每次mock 出一个task。同时 TaskModel 的 state 是1 表示已经开始review task定义参考如下：
```
class TaskModel(Document):
    meta = {"collection": "ai_codereview_task", "indexes": [("project_id", "review_version", "copy_from_version")]}

    project_id = StringField(required=True)
    review_version = StringField(required=True)
    copy_from_version = StringField(required=True)
    task_type = IntField(required=False)
    state = IntField(required=True)
    submitter = StringField(required=False)
    score = IntField(required=False, default=0)
    logic_score = IntField(required=True, default=0)
    performance_score = IntField(required=True, default=0)
    security_score = IntField(required=True, default=0)
    readable_score = IntField(required=True, default=0)
    code_style_score = IntField(required=True, default=0)
    retry_count = IntField(required=False, default=0)
    code_block_num = IntField(required=False, default=0)
    file_num = IntField(required=False, default=0)
    reviewed_file_num = IntField(required=False, default=0)
    add_code_line_num = IntField(required=False, default=0)
    comment_line_number = IntField(required=False, default=0)
    process_time = IntField(required=False, default=0)
    parent_path = StringField(required=False)  # Z:/integrity
    developer_issue_summary = DictField(required=False, default={})
    created_by = StringField(required=False, default="")
    create_time = DateTimeField(default=datetime.now(), required=True)
    updated_by = StringField(required=False, default="")
    update_time = DateTimeField(required=False)
```
### 2. 获取到一个任务后，采用ocr的实现逻辑，首先是 plan_task，需要参照 ocr 所有的实现逻辑比如，要求兼容多种语言的代码，和ocr保持一致，但是获取代码变更时，如果是增量扫描，直接通过python对比两个代码仓库所有的文件，如果发现不一样的情况（比如相同文件的md5值不一样），则可以启动对比，对比出的代码样例如下：
```
130                  temperature=0.2,
131              )
132              title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
133   -          title = title_match.group(1).strip() if title_match else "AI 汇报网页"
133   +          title = title_match.group(1).strip() if title_match else "AI 汇报网页样例"
134              return GeneratedPage(
135                  html=html,
136   -              assistant_note="页面已生成，可继续输入修改意见进行迭代。",
130   +              assistant_note="页面已生成，可继续输入修。",
130                  memory_summary=(summary_response.choices[0].message.content or "").strip(),
130                  title=title[:120],
130              )
```
请注意代码前面空出10行，1到6是数字行号字符，不够用空格补，第7个字符是+/-代表增加或删除，后面2的字符是多余的空格。对比如后保存到一份保存到数据表里，数据表如下CodeFileModel 所示，如果一个文件对比出来的代码或者所有代码 小于10000个token，则这个file 只有一个CodeBlock，代码按照行存放到 CodeBlock.contents 里，所有的代码行组成的数组。另一方面通过每种语言专用的提示词，请参照OCR的实现并增加需求给出五个维度的评分，并且在 plan_task 的时候给出这个代码块（这一次提交给大模型）评分，包含五个维度（    logic_score     performance_score security_score readable_score   code_style_score），和整体评论 CodeBlock.comment
```
class Issue(EmbeddedDocument):
    issue_id = IntField(required=False)
    description = StringField(required=True, default="")
    type = StringField(required=True, default="")
    severity = IntField(required=True, default=0)
    suggestion = StringField(required=True, default="")
    issue_line_numbers = StringField(required=False)
    issue_show = BooleanField(required=False)  # if show the issue or not
    comment_line_number = IntField(required=False, default=0)
    confidence_level = FloatField(required=False)
    re_review_description = StringField(required=False)
    re_review_status = IntField(required=False, default=0)  # 0 stands for success, other value is failed
    feedback_type = StringField(required=False)
    feedback_content = StringField(required=False)
    feedback_effect = BooleanField(required=False)


class CodeBlock(EmbeddedDocument):
    block_id = IntField(required=True, default=0)
    block_hash = StringField(required=False)
    contents = ListField(required=True)
    comment = StringField(required=True, default="")

    # logic_score performance_score security_score readable_score code_style_score
    logic_score = IntField(required=True, default=0)
    performance_score = IntField(required=True, default=0)
    security_score = IntField(required=True, default=0)
    readable_score = IntField(required=True, default=0)
    code_style_score = IntField(required=True, default=0)
    comment_line_number = IntField(required=False, default=0)
    # score = IntField(required=True, default=0)
    issues = ListField(EmbeddedDocumentField(Issue), required=False, default=[])
    process_time = IntField(required=False, default=0)
    gitlab_comment_id = StringField(required=False)
    failure_message = StringField(required=False, default="")


class CodeFileModel(Document):
    meta = {
        "collection": "ai_codereview_code_file",
        "indexes": ["project_id", ("project_id", "review_version", "copy_from_version"), "task_type"],
    }
    task_id = StringField(required=False)
    project_id = StringField(required=True)
    review_version = StringField(required=True)
    copy_from_version = StringField(required=True)
    task_type = IntField(required=False)
    file_name = StringField(required=True)
    code_blocks = ListField(EmbeddedDocumentField(CodeBlock))
    code_line_num = IntField(required=False, default=0)
    add_code_line_num = IntField(required=False, default=0)
    comment_line_number = IntField(required=False, default=0)

    logic_score = IntField(required=True, default=0)
    performance_score = IntField(required=True, default=0)
    security_score = IntField(required=True, default=0)
    readable_score = IntField(required=True, default=0)
    code_style_score = IntField(required=True, default=0)
    file_author = StringField(required=False, default="")

    created_by = StringField(required=False, default="")
    create_time = DateTimeField(default=datetime.now(), required=True)


```

#### 1. 基础系统提示词（System Prompt)
#### 2. 阶段任务指令
#### 3. 文件与规则上下文
#### 4. 目标文件完整代码
#### 5. 输出格式强约束

### 2. 进入到这个codeblock的 main_task 阶段拼接 messages 数组，tools 的实现完全参照 ocr 包括但不限于（code_search， read_file，code_comment，task_done） 。
#### 1 一、首轮 LLM 调用（main_task 第 1 次请求）：全量上下文拼装。1. 整体结构 messages 数组 + tools 参数；
#### 2 二、后续轮次 LLM 调用（工具迭代阶段）：增量追加、全量发送

#### 3 由此进入到了 function calling 阶段，实现的方式完全参照 ocr

#### 4 最后一轮调用：生成评论的结构
#### 5 把上述所有的数据，包括但不限于，在plan_task 阶段生成 comment，五个维度的评分，一起 main_task阶段生成的问题列表，issue，每个issue 有severity，description，suggestion， issue_line_numbers ，severity 是一个数字，1表示不严重，5表示最严重，这点和ocr不同，把这所以数据都保存到数据库表中CodeFileModel

### 3. 当所有的文件都已经review 结束，TaskModel 的 state 是2 ，标识已经结束这个项目的review

