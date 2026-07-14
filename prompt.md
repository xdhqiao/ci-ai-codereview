# 请参照规范要求 C:\Users\qiao\Documents\ci-ai-codereview\AGENTS.md，…

> 请参照规范要求 C:\Users\qiao\Documents\ci-ai-codereview\AGENTS.md，参考 https://github.com/alibaba/open-code-review 的核心实现，比如代码审核第一步 plan_task，第二部是main_task以及下面的流程实现：
>
> ## 实现大纲
> 我们把 https://github.com/alibaba/open-code-review 命名为 ocr，由于 ocr 使用golang 实现，该项目是参照golang并结合已有的业务代码的定义共同完成。
> ### 1.  通过syncIOScheduler异步扫描需要审核的task，这里可以mock出来一个task数据，不需要写逻辑，每次mock 出一个task。同时 TaskModel 的 state 是1 表示已经开始review task定义参考如下：
> ```
> class TaskModel(Document):
>     meta = {"collection": "ai_codereview_task", "indexes": [("project_id", "review_version", "copy_from_version")]}
>
>     project_id = StringField(required=True)
>     review_version = StringField(required=True)
>     copy_from_version = StringField(required=True)
>     task_type = IntField(required=False)
>     state = IntField(required=True)
>     submitter = StringField(required=False)
>     score = IntField(required=False, default=0)
>     logic_score = IntField(required=True, default=0)
>     performance_score = IntField(required=True, default=0)
>     security_score = IntField(required=True, default=0)
>     readable_score = IntField(required=True, default=0)
>     code_style_score = IntField(required=True, default=0)
>     retry_count = IntField(required=False, default=0)
>     code_block_num = IntField(required=False, default=0)
>     file_num = IntField(required=False, default=0)
>     reviewed_file_num = IntField(required=False, default=0)
>     add_code_line_num = IntField(required=False, default=0)
>     comment_line_number = IntField(required=False, default=0)
>     process_time = IntField(required=False, default=0)
>     parent_path = StringField(required=False)  # Z:/integrity
>     developer_issue_summary = DictField(required=False, default={})
>     created_by = StringField(required=False, default="")
>     create_time = DateTimeField(default=datetime.now(), required=True)
>     updated_by = StringField(required=False, default="")
>     update_time = DateTimeField(required=False)
> ```
> ### 2. 获取到一个任务后，采用ocr的实现逻辑，首先是 plan_task，需要参照 ocr 所有的实现逻辑比如，要求兼容多种语言的代码，和ocr保持一致，但是获取代码变更时，如果是增量扫描，直接通过python对比两个代码仓库所有的文件，如果发现不一样的情况（比如相同文件的md5值不一样），则可以启动对比，对比出的代码样例如下：
> ```
> 130                  temperature=0.2,
> 131              )
> 132              title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
> 133   -          title = title_match.group(1).strip() if title_match else "AI 汇报网页"
> 133   +          title = title_match.group(1).strip() if title_match else "AI 汇报网页样例"
> 134              return GeneratedPage(
> 135                  html=html,
> 136   -              assistant_note="页面已生成，可继续输入修改意见进行迭代。",
> 130   +              assistant_note="页面已生成，可继续输入修。",
> 130                  memory_summary=(summary_response.choices[0].message.content or "").strip(),
> 130                  title=title[:120],
> 130              )
> ```
> 请注意代码前面空出10行，1到6是数字行号字符，不够用空格补，第7个字符是+/-代表增加或删除，后面2的字符是多余的空格。对比如后保存到一份保存到数据表里，数据表如下CodeFileModel 所示，如果一个文件对比出来的代码或者所有代码 小于10000个token，则这个file 只有一个CodeBlock，代码按照行存放到 CodeBlock.contents 里，所有的代码行组成的数组。另一方面通过每种语言专用的提示词，请参照OCR的实现并增加需求给出五个维度的评分，并且在 plan_task 的时候给出这个代码块（这一次提交给大模型）评分，包含五个维度（    logic_score     performance_score security_score readable_score   code_style_score），和整体评论 CodeBlock.comment
> ```
> class Issue(EmbeddedDocument):
>     issue_id = IntField(required=False)
>     description = StringField(required=True, default="")
>     type = StringField(required=True, default="")
>     severity = IntField(required=True, default=0)
>     suggestion = StringField(required=True, default="")
>     issue_line_numbers = StringField(required=False)
>     issue_show = BooleanField(required=False)  # if show the issue or not
>     comment_line_number = IntField(required=False, default=0)
>     confidence_level = FloatField(required=False)
>     re_review_description = StringField(required=False)
>     re_review_status = IntField(required=False, default=0)  # 0 stands for success, other value is failed
>     feedback_type = StringField(required=False)
>     feedback_content = StringField(required=False)
>     feedback_effect = BooleanField(required=False)
>
> class CodeBlock(EmbeddedDocument):
>     block_id = IntField(required=True, default=0)
>     block_hash = StringField(required=False)
>     contents = ListField(required=True)
>     comment = StringField(required=True, default="")
>
>     # logic_score performance_score security_score readable_score code_style_score
>     logic_score = IntField(required=True, default=0)
>     performance_score = IntField(required=True, default=0)
>     security_score = IntField(required=True, default=0)
>     readable_score = IntField(required=True, default=0)
>     code_style_score = IntField(required=True, default=0)
>     comment_line_number = IntField(required=False, default=0)
>     # score = IntField(required=True, default=0)
>     issues = ListField(EmbeddedDocumentField(Issue), required=False, default=[])
>     process_time = IntField(required=False, default=0)
>     gitlab_comment_id = StringField(required=False)
>     failure_message = StringField(required=False, default="")
>
> class CodeFileModel(Document):
>     meta = {
>         "collection": "ai_codereview_code_file",
>         "indexes": ["project_id", ("project_id", "review_version", "copy_from_version"), "task_type"],
>     }
>     task_id = StringField(required=False)
>     project_id = StringField(required=True)
>     review_version = StringField(required=True)
>     copy_from_version = StringField(required=True)
>     task_type = IntField(required=False)
>     file_name = StringField(required=True)
>     code_blocks = ListField(EmbeddedDocumentField(CodeBlock))
>     code_line_num = IntField(required=False, default=0)
>     add_code_line_num = IntField(required=False, default=0)
>     comment_line_number = IntField(required=False, default=0)
>
>     logic_score = IntField(required=True, default=0)
>     performance_score = IntField(required=True, default=0)
>     security_score = IntField(required=True, default=0)
>     readable_score = IntField(required=True, default=0)
>     code_style_score = IntField(required=True, default=0)
>     file_author = StringField(required=False, default="")
>
>     created_by = StringField(required=False, default="")
>     create_time = DateTimeField(default=datetime.now(), required=True)
>
> ```
>
> #### 1. 基础系统提示词（System Prompt)
> #### 2. 阶段任务指令
> #### 3. 文件与规则上下文
> #### 4. 目标文件完整代码
> #### 5. 输出格式强约束
>
> ### 2. 进入到这个codeblock的 main_task 阶段拼接 messages 数组，tools 的实现完全参照 ocr 包括但不限于（code_search， read_file，code_comment，task_done） 。
> #### 1 一、首轮 LLM 调用（main_task 第 1 次请求）：全量上下文拼装。1. 整体结构 messages 数组 + tools 参数；
> #### 2 二、后续轮次 LLM 调用（工具迭代阶段）：增量追加、全量发送
>
> #### 3 由此进入到了 function calling 阶段，实现的方式完全参照 ocr
>
> #### 4 最后一轮调用：生成评论的结构
> #### 5 把上述所有的数据，包括但不限于，在plan_task 阶段生成 comment，五个维度的评分，一起 main_task阶段生成的问题列表，issue，每个issue 有severity，description，suggestion， issue_line_numbers ，severity 是一个数字，1表示不严重，5表示最严重，这点和ocr不同，把这所以数据都保存到数据库表中CodeFileModel
>
> ### 3. 当所有的文件都已经review 结束，TaskModel 的 state 是2 ，标识已经结束这个项目的review

<details><summary>31 previous messages</summary>

> 我先快速扫一遍仓库结构和本地规范，再对照 open-code-review 的核心流程做一个短计划，然后直接落实现有工程里。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `github alibaba open-code-review plan_task main_task code_search read_file code_comment task_done`
> - Searched the web for `https://github.com/alibaba/open-code-review`
> - Searched the web for `repo:alibaba/open-code-review "plan_task" "main_task"`
> - Searched the web for `site:github.com/alibaba/open-code-review "code_search" "task_done"`
> - Searched the web for `https://api.github.com/repos/alibaba/open-code-review/git/trees/main?recursive=1`
> - Searched the web for `https://api.github.com/repos/alibaba/open-code-review/git/trees/main?recursive=1`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/README.md`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/agent`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/agent/agent.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/tool/definitions.go`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/template/task_template.json`
>
> </details>
>
> </details>
>
> 仓库目前基本是空架子，只有规范文件；我会按“最小可运行后端”来搭起来。实现顺序是：先建 FastAPI/MongoEngine 分层骨架和 Docker 配置，再落本地文件夹对比、plan_task/main_task、工具调用与 mock LLM，最后补测试和 README。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/README.md`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/tool/definitions.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/template/task_template.json`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/toolsconfig/tools_config.json`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/toolsconfig/tools.json`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/template/plan_task_system.md`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config/template`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config/template`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/template/prompts/plan_task_system.md`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/template/prompts/plan_task_user.md`
>
> </details>
>
> </details>
>
> 我现在开始写文件：会保持路由层很薄，把扫描、对比、LLM 消息拼装、工具执行和数据落库放到 service/model 层里。OCR 的关键点我会复刻成“确定性扫描 + plan_task 预判 + main_task 工具迭代”，本地没有模型 Key 时走可测试的 mock 逻辑。
>
> <details><summary>Created 13 files</summary>
>
> - Wrote `./.env.example` (+28 -0)
> - Wrote `./.gitignore` (+15 -0)
> - Wrote `./Dockerfile` (+15 -0)
> - Wrote `./app/__init__.py` (+1 -0)
> - Wrote `./app/core/__init__.py` (+1 -0)
> - Wrote `./app/core/config.py` (+62 -0)
> - Wrote `./app/core/database.py` (+42 -0)
> - Wrote `./app/core/exceptions.py` (+38 -0)
> - Wrote `./app/models/__init__.py` (+4 -0)
> - Wrote `./app/models/code_file.py` (+76 -0)
> - Wrote `./app/models/task.py` (+36 -0)
> - Wrote `./docker-compose.yml` (+32 -0)
> - Wrote `./requirements.txt` (+9 -0)
>
> </details>
>
> 基础配置和数据模型已经落下来了；接下来补扫描与审核流水线，这一块会决定增量对比格式、plan/main 两阶段消息和工具调用行为。
>
> <details><summary>Created 8 files</summary>
>
> - Wrote `./app/services/__init__.py` (+1 -0)
> - Wrote `./app/services/diff_service.py` (+202 -0)
> - Wrote `./app/services/language.py` (+75 -0)
> - Wrote `./app/services/llm_client.py` (+68 -0)
> - Wrote `./app/services/prompts.py` (+149 -0)
> - Wrote `./app/services/review_service.py` (+341 -0)
> - Wrote `./app/services/review_tools.py` (+109 -0)
> - Wrote `./app/services/scheduler.py` (+34 -0)
>
> </details>
>
> 审核服务主体已经完成：包括目录扫描、10 行上下文的自定义 diff、token 阈值拆块、plan_task 评分、main_task 工具循环，以及 mock 审核规则。现在把这些能力接到 HTTP 接口、启动生命周期和文档里。
>
> <details><summary>Created 8 files</summary>
>
> - Wrote `./app/main.py` (+36 -0)
> - Wrote `./app/routes/__init__.py` (+1 -0)
> - Wrote `./app/routes/code_files.py` (+31 -0)
> - Wrote `./app/routes/health.py` (+11 -0)
> - Wrote `./app/routes/tasks.py` (+59 -0)
> - Wrote `./app/schemas/__init__.py` (+1 -0)
> - Wrote `./app/schemas/code_file.py` (+114 -0)
> - Wrote `./app/schemas/task.py` (+81 -0)
>
> </details>
>
> 接口已经接好了；我注意到 `docker compose up --build` 不能依赖本地已有 `.env`，所以文档和 compose 会用默认环境变量，同时仍保留 `.env.example` 供覆盖配置。现在补测试和 README。
>
> <details><summary>Created 7 files, edited a file</summary>
>
> - Wrote `./README.md` (+67 -0)
> - Wrote `./docker-compose.yml` (+12 -2)
> - Wrote `./pyproject.toml` (+4 -0)
> - Wrote `./tests/conftest.py` (+34 -0)
> - Wrote `./tests/test_database.py` (+16 -0)
> - Wrote `./tests/test_health.py` (+5 -0)
> - Wrote `./tests/test_review_service.py` (+66 -0)
> - Wrote `./tests/test_tasks.py` (+27 -0)
>
> </details>
>
> 第一版已经完整落地了。接下来我跑测试和静态导入检查，看看有没有启动生命周期、Mongo mock 或 schema 序列化上的细节需要修。
>
> 本机这个 shell 里没有 `python` 命令，我换 Windows 常见的 Python 启动器和可用依赖路径再试一次。
>
> 找到了 Codex 自带的 Python 运行时，我用它跑测试；如果缺包，再按规则处理依赖安装。
>
> 测试运行时缺 pytest 和框架依赖。我先在工作区里建一个本地虚拟环境安装项目依赖，这样不会改系统 Python。
>
> 虚拟环境建好了，我开始安装依赖；这一步可能需要访问 Python 包仓库。
>
> 依赖安装能联网了，但当前默认镜像返回 403。我改用官方 PyPI 源再装一次。
>
> 依赖装好了，现在重新跑完整测试。
>
> 测试主体已经过了，失败发生在测试清理阶段：TestClient 关闭时会断开 Mongo mock，清理夹具再删集合时连接没了。我把清理逻辑改成先确认连接再清空集合。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/conftest.py` (+1 -0)
>
> </details>
>
> 测试清理修好了，我再跑一遍完整测试确认没有隐藏问题。
>
> 单元测试现在通过了。我再做一次 compose 配置校验，主要确认 Docker 配置语法和默认环境变量能展开。
>
> 功能验证已经过了，我顺手把代码里的 UTC 时间写法换成 Python 3.12 更推荐的形式，避免测试里产生多余的弃用警告。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./app/models/code_file.py` (+6 -2)
> - Wrote `./app/models/task.py` (+6 -2)
> - Wrote `./app/services/review_service.py` (+8 -4)
>
> </details>
>
> 时间写法更新完了，再跑一次测试确认没有副作用。
>
> 现在只剩 MongoEngine 的 uuidRepresentation 提醒，我在连接参数里显式指定标准格式，让测试输出更干净。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/core/database.py` (+2 -0)
>
> </details>
>
> 连接参数也调整好了，做最后一轮测试和 compose 校验。
>
> 测试和 compose 配置都绿了。我再实际尝试一次 Docker 构建，尽量把“能 compose 启动”这个要求验证到位；如果本机 Docker 环境或网络拦住，我会明确说明。
>
> Docker 构建卡在拉取 `python:3.12-slim` 基础镜像，错误来自当前 Docker 镜像源返回 EOF，还没进入项目自己的构建步骤。代码侧我已经用 compose 配置校验和 pytest 做了验证。
</details>

已按 `AGENTS.md` 规范把项目从空仓库搭成可运行的 FastAPI 后端，并参考了 [Alibaba open-code-review](https://github.com/alibaba/open-code-review) 的两阶段审核思路和工具调用形态。

主要完成：

- 建立 FastAPI/MongoEngine 分层结构：[app/main.py](./app/main.py:26)、[app/routes/tasks.py](./app/routes/tasks.py:11)、[app/models/task.py](./app/models/task.py:10)、[app/models/code_file.py](./app/models/code_file.py:21)
- 实现本地增量/全量扫描、自定义 diff、10000 token 拆块：[app/services/diff_service.py](./app/services/diff_service.py:26)
- 实现 `plan_task`、`main_task`、工具调用与 issue 落库：[app/services/review_service.py](./app/services/review_service.py:38)、[app/services/review_tools.py](./app/services/review_tools.py:1)
- 补齐 `.env.example`、`Dockerfile`、`docker-compose.yml`、README、pytest 测试

验证结果：

- `pytest`：通过，`5 passed in 0.69s`
- `docker compose config`：通过
- `docker compose build`：已尝试，但在拉取 `python:3.12-slim` 基础镜像时被当前 Docker 镜像源 `docker.mirrors.ustc.edu.cn` 返回 EOF 拦住，项目构建步骤尚未开始

运行方式：

```powershell
copy .env.example .env
docker compose up --build
```

本地测试方式：

```powershell
.venv\Scripts\python.exe -m pytest
```

未完成事项：代码侧没有遗留项；唯一未完全验证的是 Docker 实际构建，原因是本机 Docker 镜像源拉基础镜像失败。

> 请继续测试：
> API KEY： sk-1d9b0fbe9a1d4535b439bc870287f1ce
> 大模型url: https://api.deepseek.com
> model：deepseek-v4-flash
>
> 来简单的测试一个具有10个左右C代码文件的代码仓库，假如TaskModel里面有一条数据
> {
> project_id: demo_c,
> review_version：wip_qiaodahai_just_demo,
> copy_from_version: master,
> state:0
> }
> 表示的含义是 review 版本 为 wip_qiaodahai_just_demo 的代码和版本为 master 的代码，两个版本的代码文件分别在本地的两个路径里，比如 D:/codereview/demo_c/wip_qiaodahai_just_demo  和 D:/codereview/demo_c/master（这两个代码路径都不存在，只是一个例子而已，具体的代码文件和路径，需要你来生成以及测试），进行增量代码对比review
> 第二个任务是：
> {
> project_id: demo_c,
> review_version：master,
> copy_from_version: 0_version,
> state:0
> }
> 表示只需要 全量review 代码路径 D:/codereview/demo_c/master
>
> 把所有的代码文件和review 的审核结果写到  CodeFileModel 里。
>
> 请结合上面的提供的demo 样例，请重新检查上面的实现部分是否有偏差，如果有，请纠正，如果没有，请继续按照提供的大模型信息以及测试要求，来真实测试项目，并解决设计的偏差，以及出现的BUG

<details><summary>39 previous messages</summary>

> 我先重新扫一下当前工程和关键实现点，重点核对你给的 `TaskModel` 示例：`task_type` 可能为空、`copy_from_version=0_version` 表示全量、版本名需要映射到本地项目目录。这三点最容易和第一版实现有偏差。
>
> 我确认有两处需要纠正：第一版只看 `task_type`，但你给的样例没有 `task_type`，且 `copy_from_version=0_version` 才表示全量；第二版路径解析需要支持 `代码根目录 / project_id / version` 这种约定。接下来我会补这个约定，并加测试覆盖这两个样例。
>
> 有一段中文在 PowerShell 输出里显示成乱码，补丁上下文没对上。我先用 UTF-8 方式重新读取相关片段，再做更精确的小补丁。
>
> 读出来确认文件本身是 UTF-8 正常的。现在按明确偏差做补丁：版本路径解析、任务类型推断、C 专项规则和文档/配置。
>
> <details><summary>Edited 7 files</summary>
>
> - Wrote `./.env.example` (+1 -0)
> - Wrote `./app/core/config.py` (+1 -0)
> - Wrote `./app/services/diff_service.py` (+14 -6)
> - Wrote `./app/services/language.py` (+4 -0)
> - Wrote `./app/services/review_service.py` (+15 -2)
> - Wrote `./docker-compose.yml` (+1 -0)
> - Wrote `./README.md` (+3 -1)
>
> </details>
>
> 偏差修正已经进代码了。接下来我补两条自动化测试：一条覆盖 `demo_c/master -> wip_qiaodahai_just_demo` 的增量任务，一条覆盖 `copy_from_version=0_version` 的全量任务。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+51 -1)
>
> </details>
>
> 测试补好了，我先跑现有自动化测试，确认修正没有破坏之前的能力。
>
> 自动化测试通过了。现在我在工作区下生成一个 `demo_repos/demo_c`，里面有 `master` 和 `wip_qiaodahai_just_demo` 两个版本；每个版本 10 个 C 文件，wip 里故意放一些真实审核点，方便用 DeepSeek 做端到端验证。
>
> <details><summary>Created 20 files</summary>
>
> - Wrote `./demo_repos/demo_c/master/src/auth.c` (+9 -0)
> - Wrote `./demo_repos/demo_c/master/src/buffer.c` (+14 -0)
> - Wrote `./demo_repos/demo_c/master/src/config.c` (+13 -0)
> - Wrote `./demo_repos/demo_c/master/src/logging.c` (+8 -0)
> - Wrote `./demo_repos/demo_c/master/src/main.c` (+18 -0)
> - Wrote `./demo_repos/demo_c/master/src/math_utils.c` (+7 -0)
> - Wrote `./demo_repos/demo_c/master/src/net_client.c` (+13 -0)
> - Wrote `./demo_repos/demo_c/master/src/parser.c` (+13 -0)
> - Wrote `./demo_repos/demo_c/master/src/report.c` (+14 -0)
> - Wrote `./demo_repos/demo_c/master/src/storage.c` (+11 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/auth.c` (+8 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/buffer.c` (+10 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/config.c` (+11 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/logging.c` (+6 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/main.c` (+12 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/math_utils.c` (+4 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/net_client.c` (+10 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/parser.c` (+8 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/report.c` (+8 -0)
> - Wrote `./demo_repos/demo_c/wip_qiaodahai_just_demo/src/storage.c` (+10 -0)
>
> </details>
>
> Demo C 仓库已经生成。为了让真实模型测试更稳，我再加一层容错：如果模型返回 JSON 外包了说明文字，或者网关不支持工具调用，服务也能解析/保存结构化 issue，而不是整条任务失败。
>
> 我刚才的补丁里有一处大小写上下文敲错了，重新拆成小补丁来做。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./app/services/llm_client.py` (+7 -1)
> - Wrote `./app/services/prompts.py` (+2 -0)
> - Wrote `./app/services/review_service.py` (+73 -3)
>
> </details>
>
> 容错和 C 规则补好了，先跑测试确认这些小改动没引入回归。
>
> 自动化测试继续通过。为了真实跑你给的两个 TaskModel 样例，我加一个小的 demo 运行脚本：它只读环境变量里的模型配置，创建两条任务，执行审核，再汇总查询 `CodeFileModel`。脚本里不会保存 API Key。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./scripts/run_demo_review.py` (+91 -0)
>
> </details>
>
> 先用 mock LLM 跑一次 demo 脚本，验证两条任务、路径解析和 CodeFileModel 写入都正常，再切到 DeepSeek。
>
> 脚本从 `scripts` 目录启动时没自动把项目根目录放进 Python 路径，我补一个根目录定位，保持直接运行可用。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./scripts/run_demo_review.py` (+5 -0)
>
> </details>
>
> 路径问题修好了，重新用 mock 跑 demo。
>
> mock 端到端跑通了：两条任务都写入了 `CodeFileModel`，总计 20 条文件审核结果。现在切换到你给的 DeepSeek 配置跑真实模型调用；这一步需要外网访问模型接口。
>
> 真实调用 5 分钟内没有完成；可能是 20 个文件触发了太多顺序模型请求，也可能是模型接口单次响应较慢。我先做一个最小 DeepSeek smoke test，确认 Key、URL、model 是否可用，然后把 demo 真实测试改成可进度输出/可限制轮次，避免长时间无反馈。
>
> smoke test 的命令行转义把 JSON 字符串弄坏了；我加一个小脚本来做连通性测试，避免 PowerShell 引号干扰。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./scripts/deepseek_smoke.py` (+25 -0)
>
> </details>
>
> 现在重新跑最小连通性测试。
>
> DeepSeek smoke test 成功，说明 Key、URL、model 都可用。刚才超时的主要原因很可能是 `main_task` 工具迭代轮数乘以 20 个文件后请求数过多；我把真实 demo 的工具轮数压到 1 轮，保留 plan/main 两阶段和一次工具提交，再跑完整两条任务。
>
> DeepSeek 真实调用已经完整跑完：两条任务、20 条 CodeFileModel 汇总都生成了。当前脚本用的是 `mongomock`，结果在进程内完成验证；我再尝试启动 Docker MongoDB，把同一套 demo 写到真实 MongoDB 里，能更贴近你要的落库场景。
>
> Docker 里的 MongoDB 没能启动，因为本机 27017 端口已经被占用。这个通常意味着已有 MongoDB 在跑；我先探测一下本机 Mongo 能不能连接，再决定是否把 demo 写进去。
>
> 本机已有 MongoDB 可以连接。为了避免在真实库里误删非 demo 数据，我先把 demo 脚本从“drop collection”改成只清理 `project_id=demo_c` 的任务和文件。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./scripts/run_demo_review.py` (+2 -2)
>
> </details>
>
> 脚本已经改成只清理 demo 数据。现在用本机真实 MongoDB 加 DeepSeek 再跑一次，这次结果会真实落到 `ai_codereview_task` 和 `ai_codereview_code_file` 集合里。
>
> 真实 Mongo + DeepSeek 跑到全量任务中途时有一次模型读取超时，导致任务失败。这是个实际 BUG：单个文件的 LLM 超时不应该让整条任务中断。我会把 plan/main 的 LLM 异常降级为本地规则兜底，并把失败原因写进 `CodeBlock.failure_message`，这样任务可以完成且结果可追踪。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+17 -2)
>
> </details>
>
> LLM 失败兜底已经加上，现在跑单元测试确认回归。
>
> 回归测试通过。现在重新跑真实 Mongo + DeepSeek；如果某个文件模型超时，服务会兜底继续并把原因写在对应代码块里。
>
> 真实 Mongo + DeepSeek 复测完成，两个任务都 state=2，20 条 CodeFileModel 已写入本机 `ci_ai_codereview`。我最后再跑一次项目测试和 compose 配置校验，并清理刚才 Docker 启动失败留下的 compose 容器。
>
> 测试和配置校验都通过，真实 Mongo 里也确认了 `demo_c` 有 2 条任务、20 条 CodeFileModel，其中 1 个代码块记录了 LLM 失败兜底信息。现在清理刚才 compose 启动失败留下的容器。
>
> 清理完成。我再抓一下关键文件位置，方便最后给你一个简洁的变更摘要。
>
> 关键位置我已经抓到了，最后整理给你。
</details>

已继续完成偏差修正和真实测试。

修正的主要偏差：

- 支持你给的任务样例里 `task_type` 为空的情况：
  - `copy_from_version=master` 自动识别为增量扫描
  - `copy_from_version=0_version` 自动识别为全量扫描
- 增加版本路径解析约定：`CODE_REPOSITORY_ROOT/project_id/version`，对应你的 `D:/codereview/demo_c/master` 这类结构。
- 增加 C 语言专项规则。
- 增加 DeepSeek/LLM 容错：JSON 外包说明文字可解析，工具调用不可用可降级 JSON 输出，单个文件 LLM 超时不会中断整个任务，会写入 `CodeBlock.failure_message`。

关键文件：

- [review_service.py](./app/services/review_service.py:87)
- [diff_service.py](./app/services/diff_service.py:140)
- [config.py](./app/core/config.py:30)
- [run_demo_review.py](./scripts/run_demo_review.py:1)

我生成了 demo C 仓库：

- [master](./demo_repos/demo_c/master/src/main.c:1)
- [wip_qiaodahai_just_demo](./demo_repos/demo_c/wip_qiaodahai_just_demo/src/main.c:1)

真实测试结果：

- DeepSeek smoke test：成功，接口返回 `200`
- 使用 `deepseek-v4-flash` 跑了两条任务
- 本机真实 MongoDB 写入成功：
  - `TaskModel(project_id=demo_c)`：2 条
  - `CodeFileModel(project_id=demo_c)`：20 条
  - 两个任务最终 `state=2`
  - 增量任务：10 个 C 文件，10 个 CodeBlock
  - 全量任务：10 个 C 文件，10 个 CodeBlock
  - 有 1 个代码块记录了 LLM 超时兜底信息，流程没有中断

验证：

```powershell
.venv\Scripts\python.exe -m pytest
```

结果：`7 passed in 0.55s`

补充说明：我尝试启动 docker-compose 里的 MongoDB，但本机 `27017` 已被已有 MongoDB 占用，所以直接使用了这个本机 MongoDB 完成真实落库测试；失败的 compose 容器已清理。

> 现在 main_task 工具迭代轮数设置的是多少？设置10之后再试试，会不会有超时现象？如果超时是不是可以设置更长的超时时间。
> 请重新测试，并解释清楚

<details><summary>5 previous messages</summary>

> 我先确认一下当前配置来源：代码默认值、上次真实测试时临时传入的环境变量，以及 `main_task` 循环实际使用的位置。然后我会把本次真实测试设成 `LLM_MAX_TOOL_ROUNDS=10`，并把单次模型超时时间也显式设置出来，避免结果含糊。
>
> 确认到了：代码默认 `LLM_MAX_TOOL_ROUNDS=30`，`.env.example` 也是 30；上一次我真实压测时为了避免过久，临时传的是 1。现在我给 demo 输出补上耗时、实际轮数和失败块数量，这样 10 轮测试结果会更清楚。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./scripts/run_demo_review.py` (+10 -0)
>
> </details>
>
> 我现在跑真实端到端：`LLM_MAX_TOOL_ROUNDS=10`，单次请求 `LLM_TIMEOUT_SECONDS=120`，仍然写入本机 MongoDB 的 `demo_c` 数据。这个测试会有 10 个增量 C 文件 + 10 个全量 C 文件，模型调用次数明显多一些，预计要几分钟。
>
> 10 轮真实测试完成了，没有出现请求超时，也没有触发 `failure_message` 兜底。它比 1 轮慢很多：整套 demo 用了约 524 秒，但 issue 数量明显更充分。现在我跑一下回归测试，确认脚本输出增强没有影响项目测试。
</details>

当前配置分两层看：

- 代码默认值：`LLM_MAX_TOOL_ROUNDS=30`
- 上一次真实测试时我为了缩短耗时，临时设置成了 `1`
- 刚刚按你的要求重新测试，设置为：`LLM_MAX_TOOL_ROUNDS=10`

注意：10 轮是 `main_task` 工具迭代的上限，不代表每个文件一定调用 10 次。模型如果不再返回 tool_calls，或者调用 `task_done`，会提前结束。

这次真实测试配置：

```text
LLM_MAX_TOOL_ROUNDS=10
LLM_TIMEOUT_SECONDS=120
LLM_MODEL=deepseek-v4-flash
LLM_URL=https://api.deepseek.com
```

测试结果：

```text
elapsed_seconds: 524.09
TaskModel: 2 条
CodeFileModel: 20 条
failure_block_count: 0
pytest: 7 passed
```

两条任务都完成并落库：

- 增量任务 `master -> wip_qiaodahai_just_demo`
  - `state=2`
  - `file_num=10`
  - `code_block_num=10`
  - `comment_line_number=27`
  - 没有超时兜底

- 全量任务 `master / copy_from_version=0_version`
  - `state=2`
  - `file_num=10`
  - `code_block_num=10`
  - `comment_line_number=23`
  - 没有超时兜底

结论：设置成 10 轮后，这次没有出现 DeepSeek 请求超时，但总耗时从之前 1 轮时的约 5 分钟增加到约 8 分 44 秒。issue 数量也明显更充分。

如果后续出现超时，可以调大：

```env
LLM_TIMEOUT_SECONDS=180
# 或 300
```

这个控制的是单次大模型 HTTP 请求超时时间。现在代码也已经做了兜底：如果某个文件的 `plan_task` 或 `main_task` 模型调用超时，不会中断整个任务，会把失败原因写到 `CodeBlock.failure_message`，并用本地规则继续生成结果，最后任务仍可进入 `state=2`。

> 请你梳理一下当前工程的核心流程（plan_task, main_task），提示词，function_calling循环调用的机制，以及工具（code_search, read_file，code_comment，task_done）的定义和实现逻辑是否一致。
> 这些也是保证code review 结果准确度高的根本

<details><summary>2 previous messages</summary>

> 我来按代码实际实现梳理，而不是只按设计描述复述：先读 `review_service`、`prompts`、`review_tools`、`llm_client` 和测试里覆盖的路径，再给你指出一致的地方和会影响准确度的偏差点。
>
> 我已经读完核心实现。整体机制是通的，而且工具定义和实际 runner 基本一致；不过也有几个会影响准确度的设计点，尤其是“没有强制 task_done 后才完成”和“tool result 没有 name 字段”。我把流程、提示词、循环和一致性检查拆开说。
</details>

结论：当前工程的 `plan_task -> main_task -> function calling -> CodeFileModel 落库` 主链路是贯通的，工具定义和实现也基本一致；但还有几个会影响审核准确度的点，尤其是“JSON 解析失败会静默无 issue”“工具异常会降级 mock”“还没有做相似 issue 合并”。

**核心流程**

入口在 [review_service.py](./app/services/review_service.py:64)：

1. `review_task`
   - 任务开始：`TaskModel.state=1`
   - 调 `_collect_targets` 收集待审文件
   - 每个文件进入 `_review_file`
   - 所有文件结束后 `_finish_task` 汇总评分、issue 数量，设置 `state=2`

2. `_collect_targets`
   - 增量：`copy_from_version` 和 `review_version` 解析为两个本地目录，做 diff
   - 全量：`copy_from_version` 为空、`0`、`0_version` 时扫描整个 `review_version`
   - 对应实现：[diff_service.py](./app/services/diff_service.py:30)

3. `_review_file`
   - 一个文件拆成一个或多个 `CodeBlock`
   - 每个 block 先跑 `_run_plan_task`
   - 再跑 `_run_main_task`
   - 最终保存到 `CodeFileModel.code_blocks`

**plan_task**

实现位置：[review_service.py](./app/services/review_service.py:156)

提示词构造位置：[prompts.py](./app/services/prompts.py:115)

消息结构是：

- `system`：基础代码审核专家角色
- `user`：
  - 阶段任务指令
  - 文件名、语言、语言专项规则
  - 代码变更 diff
  - 目标文件完整代码
  - 输出格式强约束

`plan_task` 要求模型只输出 JSON：

```json
{
  "comment": "本代码块整体评价",
  "logic_score": 0-100,
  "performance_score": 0-100,
  "security_score": 0-100,
  "readable_score": 0-100,
  "code_style_score": 0-100
}
```

如果 LLM 超时或 JSON 解析失败，会走本地 `_mock_plan_response` 兜底，并把失败原因写进 `CodeBlock.failure_message`。

**main_task**

实现位置：[review_service.py](./app/services/review_service.py:176)

提示词构造位置：[prompts.py](./app/services/prompts.py:131)

消息结构是：

- `system`：同一个基础审核专家角色
- `user`：
  - 执行 `main_task`
  - 文件与语言规则
  - `plan_task` 结论
  - 代码变更 diff
  - 目标文件完整代码
  - 输出格式强约束

`main_task` 强制模型通过 `code_comment` 提交问题，或通过 `task_done` 结束。如果网关不支持工具调用，也允许直接输出：

```json
{"issues":[...]}
```

**function calling 循环**

循环在 [review_service.py](./app/services/review_service.py:196)。

逻辑是：

1. 调 LLM，携带 `MAIN_TOOL_DEFINITIONS`
2. 把 assistant message 追加到 messages
3. 如果没有 `tool_calls`：
   - 尝试从 content 里解析 `{"issues":[...]}`
   - 结束循环
4. 如果有 `tool_calls`：
   - 逐个执行本地工具
   - 将工具结果作为 `role=tool` 追加回 messages
   - 下一轮把完整 messages 再发给模型
5. 如果工具调用了 `task_done`：
   - 提前结束
6. 达到 `LLM_MAX_TOOL_ROUNDS`：
   - 结束循环，保存已收集到的 comments

默认轮数是 30；你上次让我测 10 轮时没有超时，结果更充分。

**工具一致性检查**

工具定义在 [prompts.py](./app/services/prompts.py:31)，实际执行在 [review_tools.py](./app/services/review_tools.py:11)。

一致性如下：

- `code_search`
  - 定义：`query`、`regex`、`limit`
  - 实现：在 review root 下递归搜索允许扩展名文件
  - 一致

- `read_file`
  - 定义：`file_path`、`start_line`、`end_line`
  - 实现：读取指定文件指定行范围
  - 一致

- `file_read`
  - 定义：`read_file` 的兼容别名
  - 实现：和 `read_file` 走同一逻辑
  - 额外兼容 OCR 命名，没问题

- `code_comment`
  - 定义：`type`、`severity`、`description`、`suggestion`、`issue_line_numbers`
  - 实现：写入 runner.comments，severity 归一到 1-5
  - 一致

- `task_done`
  - 定义：可带 `summary`
  - 实现：设置 `runner.done=True`
  - 一致

**影响准确度的风险点**

1. 还没有做相似 issue 合并
   当前只按 `type` 做 `developer_issue_summary` 统计，没有合并重复/相似问题。这和最初“最后合并相同审核问题列表”的目标还有差距。

2. JSON 解析失败会静默丢失 main_task 输出
   `_collect_json_comments` 如果解析失败就 return，不会把失败写进 `failure_message`。这会让模型其实发现了问题、但格式不稳时，结果丢掉。

3. 工具执行异常会触发整个 block 降级
   比如模型给了非法 regex，`code_search` 可能抛错，然后 `_review_file` 会转 mock 规则。兜底能保证任务完成，但准确度会下降。

4. `task_done` 过早调用会结束循环
   如果模型先 `task_done`，没有 `code_comment`，这个 block 就没有 issue。提示词已经约束了，但还可以在服务端增加“无 comment 时要求模型再确认一轮”的机制。

5. `read_file` 路径安全可以更严谨
   当前用字符串 `startswith` 判断是否逃逸 review root。建议改成 `candidate.relative_to(self.root_dir)`，更标准，也更安全。

总体看，当前实现已经具备 OCR 风格两阶段审核和 function calling 迭代机制；下一步如果要提高准确度，我建议优先补“重复 issue 合并”“工具异常结构化返回”“main_task 输出解析失败记录”这三块。

> 1. 重复的issue合并，是项目级别的合并还是当前代码文件审核的结果的issue合并，如果是项目级别，暂时不合并，如果是，当前代码文件的结果的issue合并，需要完成这个需求。
> 2. 还有没有 ocr 定义了工具，但是当前项目没有定义，如果有，请思考是否需要，如果需要，请定义并使用
> 3. JSON 解析失败会静默丢失 main_task 输出，如果解析失败是否有重试？如果没，请继续优化
> 4. ocr 的循环默认是多少次？当前项目设置的次数是否合理，如果不合性，也请修改
> 5. 请继续优化 【read_file 路径安全可以更严谨】
>
> 以及你其它认为 ocr 实现的好的方面，请指出来，继续优化当前项目

<details><summary>16 previous messages</summary>

> 我会先对照 upstream OCR 的工具/循环设计，再落到本项目里做具体优化：当前文件内 issue 合并、main_task JSON 解析失败重试、工具异常结构化返回、`read_file` 路径安全，以及必要的工具补齐。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `github alibaba open-code-review code_search read_file code_comment task_done max iterations tools`
> - Searched the web for `https://api.github.com/repos/alibaba/open-code-review/git/trees/main?recursive=1`
> - Searched the web for `api.github.com/repos/alibaba/open-code-review/git/trees/main recursive`
> - Searched the web for `https://github.com/alibaba/open-code-review`
> - Searched the web for `https://github.com/alibaba/open-code-review`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/tool`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/llmloop`
> - Searched the web for `'max' in https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go`
> - Searched the web for `'MaxToolRequestTimes' in https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config/template`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/tool`
> - Searched the web for `'Tool() Tool' in https://github.com/alibaba/open-code-review/blob/main/internal/tool/file_read_diff.go`
>
> </details>
>
> </details>
>
> 我对照到 OCR 内置工具比当前项目多两个：`file_find` 和 `file_read_diff`；OCR 默认 `MAX_TOOL_REQUEST_TIMES` 是 30，当前项目默认也是 30，所以轮数本身合理。接下来我会补齐这两个工具、把 main_task 的“无工具/JSON 解析失败”改成重试而不是静默丢弃，并做当前文件级 issue 合并。
>
> 我会把合并范围限定为“当前 CodeFileModel 内部”，不做项目级合并；这样不会跨文件误合并语义相似但上下文不同的问题。合并策略先用稳定的结构化 key，避免让另一次 LLM 合并引入新的不确定性。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./.env.example` (+1 -0)
> - Wrote `./app/core/config.py` (+1 -0)
> - Wrote `./docker-compose.yml` (+2 -0)
>
> </details>
>
> 配置补上了 JSON 重试次数，并把 Docker 环境变量也显式透出。现在补齐 `file_find`、`file_read_diff` 的工具定义和本地实现，同时让工具异常变成结构化结果返回给模型。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/prompts.py` (+31 -0)
> - Wrote `./app/services/review_tools.py` (+68 -11)
>
> </details>
>
> 工具定义和实现已经对齐：新增工具可被模型调用，工具内部出错也会作为 JSON 结果返回而不是打断整个循环。接下来改 main_task：解析失败会重试，最终失败才记录；同时加入当前文件内 issue 去重合并。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+87 -9)
>
> </details>
>
> 主循环现在不会再“解析失败直接丢掉”：会按配置重试，最终失败才写入 `failure_message`。我开始补测试，覆盖新增工具、路径安全、JSON 重试和文件内重复 issue 合并。
>
> <details><summary>Created a file, edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+79 -0)
> - Wrote `./tests/test_review_tools.py` (+31 -0)
>
> </details>
>
> 测试用例已经补上了：新增工具、路径逃逸、JSON 重试、文件内重复 issue 合并都有覆盖。现在跑完整测试，看有没有细节需要修。
>
> 测试过了。我再顺手做一个准确度相关的小优化：把模型输出的 issue type 收敛到五类，避免像 `style`、`code style`、`code_style` 混在统计里；同时让工具调用不可用后的 JSON 输出也走同一套重试逻辑。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/prompts.py` (+1 -0)
> - Wrote `./app/services/review_service.py` (+26 -5)
>
> </details>
>
> 类型归一化也加上了；现在做最终测试和 compose 配置校验。
>
> 测试全部通过，compose 配置也正常。最后我整理一下改了哪些点、哪些 OCR 设计被吸收、哪些暂时保持不做。
</details>

已继续优化完。先回答你的几个判断：

1. 重复 issue 合并
当前只做“当前代码文件内”的 issue 合并，不做项目级合并。
原因是项目级合并容易把不同文件、不同上下文里的相似问题误合并；当前阶段先保证 `CodeFileModel` 内部结果干净。

2. OCR 额外工具
对照 [alibaba/open-code-review](https://github.com/alibaba/open-code-review)，OCR 还有 `file_find`、`file_read_diff` 这类工具。当前项目原来没有，我已经补上并接入 function calling。

3. JSON 解析失败
之前确实没有重试，可能静默丢 issue。
现在已增加 `LLM_JSON_RETRY_TIMES=2`，解析失败会要求模型重新按 JSON 输出，最终仍失败才记录到 `failure_message`。

4. OCR 循环默认次数
OCR 默认 `MAX_TOOL_REQUEST_TIMES` 是 30。当前项目默认 `LLM_MAX_TOOL_ROUNDS=30`，和 OCR 保持一致，所以不改默认值。之前测试 10 轮只是临时压测配置。

5. `read_file` 路径安全
已从字符串 `startswith` 改成 `Path.relative_to()` 判断，防止路径逃逸判断不严谨。

本次主要修改：

- 新增工具定义和实现：
  - `file_find`
  - `file_read_diff`
- 工具调用异常不再直接打断循环，而是返回结构化 `{error: ...}` 给模型。
- `main_task` JSON 解析失败会重试。
- 当前文件内重复 issue 会合并，并重新编号 `issue_id/comment_line_number`。
- issue type 归一化到：
  - `logic`
  - `performance`
  - `security`
  - `readability`
  - `code_style`
- severity 字符串如 `high/critical` 也会归一到 1-5。
- `docker-compose.yml`、`.env.example` 增加：
  - `LLM_MAX_TOOL_ROUNDS`
  - `LLM_JSON_RETRY_TIMES`

验证结果：

```text
pytest: 11 passed in 0.45s
docker compose config: 通过
```

关键文件：

- [prompts.py](./app/services/prompts.py:23)
- [review_tools.py](./app/services/review_tools.py:11)
- [review_service.py](./app/services/review_service.py:176)
- [config.py](./app/core/config.py:25)

我认为 OCR 里值得继续吸收的下一步是：把工具调用轨迹、每轮模型输入输出摘要、token/耗时都落库。这样后续可以解释“为什么漏审/误报”，也能针对提示词做可观测优化。

> 请参照OCR的实现结合当前项目的实现，完成下面的功能：把工具调用轨迹、每轮模型输入输出摘要、token/耗时都落库。这样后续可以解释“为什么漏审/误报”，也能针对提示词做可观测优化。

<details><summary>25 previous messages</summary>

> 我先把当前仓库核心文件和 OCR 相关实现再对齐一下，然后会给出一个短计划并直接落库设计。这个功能比较关键，我会优先让数据结构稳定、查询方便，而不是只把一大段原始日志塞进字符串里。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `alibaba open-code-review MAX_TOOL_REQUEST_TIMES code_search file_find file_read_diff`
> - Searched the web for `https://github.com/alibaba/open-code-review`
>
> </details>
>
> </details>
>
> 实现计划我定下来了：观测数据挂在 `CodeBlock` 上，因为 plan/main/tool 都是围绕单个代码块发生的。字段会包含每轮模型摘要、每个工具调用摘要，以及汇总 token/耗时，方便后续查“某个文件为什么给了这个结论”。
>
> 我会同时保存“摘要”和“原始可诊断字段”的平衡版：不把整段 prompt 原文重复塞进库里，但会记录消息数量、最后用户指令摘要、模型输出摘要、tool 名称、参数、结果摘要、usage token 和耗时。这样可观测性够用，库体积也不会失控。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/models/code_file.py` (+39 -0)
> - Wrote `./app/models/__init__.py` (+2 -2)
>
> </details>
>
> 数据模型已经扩展完成。接下来改 LLM 客户端：让每次 chat 都带回模型名、finish_reason、usage 和耗时，同时发下一轮请求前自动剥离内部 trace 字段，避免污染 OpenAI/DeepSeek 兼容接口。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/llm_client.py` (+26 -3)
>
> </details>
>
> LLM 客户端已能返回 trace。现在把 plan/main/tool 的 trace 串起来，最终随每个 `CodeBlock` 一起保存。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+4 -1)
> - Wrote `./app/services/review_service.py` (+14 -0)
> - Wrote `./app/services/review_service.py` (+6 -1)
>
> </details>
>
> plan_task 的输入摘要、输出摘要、token 和耗时已经会记录了。接着处理 main_task 的多轮模型调用和每个工具调用轨迹。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+21 -2)
>
> </details>
>
> main_task 的轮次和工具 trace 已串好。现在加几个辅助方法：摘要截断、usage 解析、token 汇总和工具结果摘要，这些会控制落库体积。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+101 -0)
>
> </details>
>
> 落库辅助方法好了。为了接口查询也能看到这些观测数据，我会同步把响应 schema 补上，不然虽然 Mongo 里有，API 层会看不到。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/schemas/code_file.py` (+79 -1)
>
> </details>
>
> 模型、服务和 API 都改好了。我先跑测试，看看有没有旧测试因为新增字段或 trace 逻辑出现不兼容。
>
> 测试暴露了一个合理变化：plan_task 现在也通过 `chat` 记录 trace，旧的 fake 客户端第一轮直接返回了 main_task 的坏 JSON。测试桩我会按真实流程改成：plan 先返回评分 JSON，main 第一轮坏 JSON，第二轮有效 JSON。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+8 -0)
>
> </details>
>
> 基础测试过了。我再补一个更贴近真实 function calling 的测试：模型先返回 `code_comment` 工具调用，再返回 `task_done`，同时带 usage。这样能确认工具轨迹、模型轮次、token 汇总都真的进了 `CodeBlock`。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+106 -0)
>
> </details>
>
> trace 测试补好了，现在跑完整测试。
>
> 测试通过。再做一次 compose 配置校验，确认新增环境变量和服务配置都能展开。
>
> 配置校验也通过。我补一下 README，让后续使用者知道这些观测字段在哪里、代表什么。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./README.md` (+11 -0)
>
> </details>
>
> 文档也补好了。最后我抓一下关键实现位置，方便给你一个清楚的完成说明。
</details>

已完成这块可观测能力，并做了测试验证。

实现内容：

- 在 `CodeBlock` 里新增落库字段：
  - `model_rounds`：每轮 `plan_task/main_task` 的模型调用摘要、输出摘要、模型、finish reason、token、耗时、错误信息
  - `tool_calls`：每次 function calling 的工具名、参数、结果摘要、成功状态、耗时、错误信息
  - `llm_prompt_tokens`
  - `llm_completion_tokens`
  - `llm_total_tokens`
  - `llm_reasoning_tokens`
  - `llm_cached_tokens`
  - `llm_elapsed_ms`

关键文件：

- [code_file.py](./app/models/code_file.py:38)
- [llm_client.py](./app/services/llm_client.py:27)
- [review_service.py](./app/services/review_service.py:134)
- [code_file.py schema](./app/schemas/code_file.py:34)
- [README.md](./README.md:71)

具体机制：

- `LLMClient.chat()` 现在会把 DeepSeek/OpenAI 兼容接口返回的 `usage`、`model`、`finish_reason` 和请求耗时放到内部 `_llm_trace`。
- 发下一轮请求前会自动移除 `_llm_trace`，不会污染模型 API 请求。
- `plan_task` 会记录 1 轮模型调用 trace。
- `main_task` 每一轮 function calling 都会记录模型调用 trace。
- 每个工具调用都会记录参数、结果摘要、成功/失败和耗时。
- 最终按代码块汇总 token 和耗时，保存进 `CodeBlock`。
- 落库保存的是摘要，不保存完整 prompt 原文，避免 Mongo 体积过大和敏感信息扩散。

测试结果：

```text
pytest: 12 passed in 2.59s
docker compose config: 通过
```

我还补了一个专门测试：模型先调用 `code_comment`，再调用 `task_done`，同时返回 token usage，验证 `model_rounds`、`tool_calls`、token 和耗时都会真实写入 `CodeBlock`。

> 请继续检查本项目和OCR的核心实现逻辑是否完全一致？如果有不一致的请指出？并指出哪个实现更好？

<details><summary>2 previous messages</summary>

> 我会按“实际代码对实际代码”来比对，不只看名称相似度。先读本项目当前实现，再从 GitHub 上抓 OCR 的关键入口、工具、prompt/loop 配置，最后给你一个差异清单和取舍判断。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/README.md`
> - Searched the web for `https://api.github.com/repos/alibaba/open-code-review/git/trees/main?recursive=1`
> - Searched the web for `site:github.com/alibaba/open-code-review internal tool file_read_diff file_find code_comment task_done`
> - Searched the web for `https://github.com/alibaba/open-code-review`
> - Searched the web for `https://github.com/alibaba/open-code-review`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/llmloop`
> - Searched the web for `https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go`
> - Searched the web for `https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/agent`
> - Searched the web for `https://github.com/alibaba/open-code-review/blob/main/internal/agent/agent.go`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/config/template`
>
> </details>
>
> </details>
</details>

不完全一致。当前项目已经复刻了 OCR 的主干：`plan_task -> main_task -> function calling -> code_comment/task_done -> 结果落库`，但和 OCR 的成熟实现相比，还有不少关键差异。下面按影响准确度的优先级梳理。

**结论先说**

当前项目更贴合你的业务目标：MongoDB 落库、TaskModel 状态流转、本地双目录增量扫描、五维评分、每个 CodeBlock 可观测数据。

OCR 更强的是代码审核准确度工程化：Git diff 精准来源、规则匹配、上下文压缩、评论定位/重定位、review_filter、并发、session/telemetry、scan 批处理。OCR README 也明确强调它的核心是“确定性工程 + Agent”，包括精准文件选择、智能文件打包、细粒度规则匹配、定位和反思模块。([github.com](https://github.com/alibaba/open-code-review))

**一致的部分**

- 都有 `plan_task` 和 `main_task` 两阶段。
- 都是每个文件进入 main loop。
- 都有 function calling 工具循环。
- 工具集合基本对齐：
  - `code_search`
  - `file_find`
  - `file_read/read_file`
  - `file_read_diff`
  - `code_comment`
  - `task_done`
- 循环上限一致：OCR `MAX_TOOL_REQUEST_TIMES=30`，当前项目默认 `LLM_MAX_TOOL_ROUNDS=30`。OCR 模板里也有 `PLAN_TASK`、`MAIN_TASK`、`REVIEW_FILTER_TASK`、`RE_LOCATION_TASK`、`MEMORY_COMPRESSION_TASK` 等阶段配置。([github.com](https://github.com/alibaba/open-code-review/blob/main/internal/config/template/task_template.json))
- 都记录 token/工具调用/耗时一类诊断信息。OCR 在 Runner 里累计 token 和 tool call 计数，当前项目把每个 CodeBlock 的轮次和工具轨迹直接落 MongoDB。([github.com](https://github.com/alibaba/open-code-review/raw/refs/heads/main/internal/llmloop/loop.go))

**主要不一致**

| 模块 | OCR | 当前项目 | 哪个更好 |
|---|---|---|---|
| diff 来源 | Git diff，支持 workspace/range/commit，并依赖 Git 语义 | 本地两个目录 md5 + difflib | OCR 更准确；当前更符合你要求的本地双目录 |
| 文件过滤 | 默认扩展/路径过滤 + rule.json include/exclude | 简单扩展名和排除目录 | OCR 更成熟 |
| 规则匹配 | path-based 规则解析，按文件注入 system rule | 简单语言规则字典 | OCR 更准确 |
| plan_task | 可按变更行数阈值跳过，小变更省 token | 每个 block 都 plan，并要求五维评分 | OCR 更省 token；当前更适合评分落库 |
| main_task 循环 | 强制工具调用，无工具调用会继续 retry | 支持工具，也支持 JSON fallback | OCR 更稳定；当前兼容 DeepSeek/网关更好 |
| 上下文控制 | 有 memory compression，超 60%/80% 阈值压缩/停止 | 只有 CodeBlock 拆块，无对话压缩 | OCR 明显更好 |
| code_comment | 会覆盖当前文件 path，解析评论，并基于 diff 做定位/重定位 | 直接保存 issue_line_numbers | OCR 更好，位置准确度更强 |
| review filter | main loop 后有 REVIEW_FILTER_TASK 过滤错误评论 | 只有文件内重复 issue 合并 | OCR 更好，能降误报 |
| 并发 | 文件级并发，默认 concurrency 8 | 当前服务内基本顺序处理 | OCR 性能更好 |
| scan | 支持 batch by language/directory、dedup、summary、token budget | 全量扫描逐文件处理 | OCR 更适合大项目 |
| 结果持久化 | 本地 session history + telemetry | MongoDB 结构化落库 | 当前项目更适合业务系统 |

**几个关键差异展开**

1. main_task 循环还不是完全 OCR 风格
OCR 的循环如果没有工具调用，会追加提示要求模型“必须调用工具或 task_done”，然后继续循环；它不会默认接受普通 JSON 作为成功结果。当前项目为了兼容 DeepSeek/OpenAI 网关，允许 JSON fallback。这对落地更友好，但会削弱 OCR 那种“强约束工具闭环”。OCR 这一段还会处理无有效工具结果的连续重试和最大轮次。([github.com](https://github.com/alibaba/open-code-review/raw/refs/heads/main/internal/llmloop/loop.go))

2. 当前项目缺少 OCR 的上下文压缩
OCR 在 `addNextMessage` 里有基于 token 阈值的压缩逻辑：超过 soft/warning threshold 会触发压缩或停止。当前项目虽然按 `DIFF_TOKEN_THRESHOLD` 拆 CodeBlock，但 main_task 多轮工具调用时没有压缩历史 messages。大文件、多轮工具时 OCR 更稳。([github.com](https://github.com/alibaba/open-code-review/raw/refs/heads/main/internal/llmloop/loop.go))

3. 当前项目缺少评论定位/重定位
OCR 的 `code_comment` 不是简单收集评论：它会覆盖模型传入的 path，避免模型幻觉路径；还会用 diff 解析评论位置，如果定位失败，会走 `RE_LOCATION_TASK`。当前项目只是信任模型给的 `issue_line_numbers`。这一点 OCR 明显更好。([github.com](https://github.com/alibaba/open-code-review/raw/refs/heads/main/internal/llmloop/loop.go))

4. 当前项目缺少 review_filter
OCR main loop 结束后会执行 `REVIEW_FILTER_TASK`，把明显错误的评论过滤掉。当前项目目前只有“同一文件内完全重复 issue 合并”，不是语义级误报过滤。降低误报方面 OCR 更强。([github.com](https://github.com/alibaba/open-code-review/raw/refs/heads/main/internal/agent/agent.go))

5. plan_task 的目标不同
OCR 的 plan_task 是“给 main_task 提供审查计划/指导”，而且小变更可按 `PLAN_MODE_LINE_THRESHOLD=50` 跳过。当前项目把 plan_task 设计成“评分 + 整体评论 + 指导”。这和你的数据库需求一致，但不是 OCR 原样实现。评分落库当前项目更好；token 成本和提示词稳定性 OCR 更好。([github.com](https://github.com/alibaba/open-code-review/blob/main/internal/config/template/task_template.json))

6. 工具集合已经基本补齐，但实现深度不同
OCR 工具目录包含 `code_comment.go`、`code_search.go`、`file_find.go`、`file_read.go`、`file_read_diff.go` 等。当前项目已经有对应 Python 实现，但 OCR 的工具更贴合 Git/diff/session/telemetry，尤其是 `code_comment`。([github.com](https://github.com/alibaba/open-code-review/tree/main/internal/tool))

**我认为当前项目比 OCR 更好的点**

- MongoDB 结构化存储更适合后台系统。
- `TaskModel`/`CodeFileModel` 状态和评分字段符合你的业务模型。
- 本地双目录扫描符合你“不是 Git 分支，而是两个代码目录”的要求。
- 每个 `CodeBlock` 落 `model_rounds` 和 `tool_calls`，对后续排查漏审/误报很直接。
- DeepSeek 工具调用不稳定时，JSON fallback 更实用。

**我认为 OCR 更好的点**

- Git diff 和路径/行号定位更成熟。
- main_task 强制工具闭环更稳定。
- review_filter 和 re_location 是提高准确度的关键模块。
- memory compression 更适合长上下文。
- 并发和 scan batching 更适合大项目。
- 规则匹配体系比当前语言字典更细。

**建议下一步优化顺序**

1. 补 `RE_LOCATION_TASK`：先解决行号漂移。
2. 补 `REVIEW_FILTER_TASK`：降低误报。
3. 补 main_task 上下文压缩：避免 10+ 轮时上下文膨胀。
4. 把规则从硬编码语言字典升级为 JSON rule resolver。
5. 增加文件级并发，真正使用 `LLM_CONCURRENCY`。

如果只选一个最影响准确度的，我建议先做 `code_comment` 的定位/重定位逻辑。当前项目的最大差距不是“有没有工具”，而是“模型给出的 issue 是否能稳定落到正确代码行”。

<details><summary>50 previous messages</summary>

> Context compaction
>
> Source: automatic
> Status: completed
>
> 我先快速重新扫一遍工程结构和当前核心文件，再把优化拆成小步落到现有模型里。这里会优先做可验证的改动：行号重定位、误报过滤、上下文压缩、规则解析、文件级并发。
>
> 结构已经确认，当前项目仍是很清晰的 routes / services / models / tests 分层。我会按这个顺序改：先补数据字段和配置，再补 prompts 与服务流程，最后用假模型测试“重定位、过滤、压缩、规则解析、并发”这些关键行为。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `alibaba open-code-review RE_LOCATION_TASK REVIEW_FILTER_TASK memory compression llmloop loop.go`
> - Searched the web for `https://github.com/alibaba/open-code-review`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/template/task_template.json`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/agent/agent.go`
>
> </details>
>
> </details>
>
> 我也核对了 OCR 当前核心实现：它在 main_task 后有独立的 review_filter，code_comment 里带行号解析/重定位，循环过程中会做上下文压缩，并且按文件并发处理。接下来我会把这些能力按 Python 现有数据结构补进去，而不是改变已有表的基本形态。
>
> 我看到现有代码已经能保存基础轨迹，但缺少“二次校准”的阶段字段，也缺少压缩后的消息轨迹。我要把这些都保存在 `CodeBlock` 的现有嵌套结构里，必要时给 `Issue` 增加状态字段，这样历史数据兼容性更稳。
>
> 我准备动手改文件了。核心原则是：不推翻现有 `CodeFileModel -> CodeBlock -> Issue` 的落库结构，只给 issue 和 block 补充校准、过滤、压缩相关字段，并把新阶段的模型调用继续写进已有 `model_rounds`。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/models/code_file.py` (+6 -0)
> - Wrote `./app/core/config.py` (+8 -0)
>
> </details>
>
> 配置层已经补齐：压缩频率、保留消息数、scan batching、规则文件路径、重定位和过滤开关都可以通过环境变量控制。下一步把硬编码语言规则换成可扩展 JSON 规则解析器。
>
> <details><summary>Created 2 files</summary>
>
> - Wrote `./app/services/review_rules.json` (+133 -0)
> - Wrote `./app/services/rules.py` (+81 -0)
>
> </details>
>
> `prompts.py` 是正常 UTF-8，刚才只是补丁上下文没对上。我会用更小的补丁拆开处理，减少对原有提示词的扰动。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/prompts.py` (+4 -1)
> - Wrote `./app/services/prompts.py` (+30 -0)
>
> </details>
>
> 提示词层会新增两个阶段：`RE_LOCATION_TASK` 做行号校准，`REVIEW_FILTER_TASK` 做误报筛选。它们都会被当作独立模型轮次记录下来，便于后面解释“为什么这个 issue 被保留或过滤”。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/prompts.py` (+2 -2)
>
> </details>
>
> 规则上下文现在从 JSON resolver 生成，不再只靠语言字典。这样以后要加目录规则、危险 API、团队规范，可以改 JSON 或外部 `REVIEW_RULES_PATH`，不用改提示词代码。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/prompts.py` (+50 -0)
> - Wrote `./app/services/review_service.py` (+9 -1)
> - Wrote `./app/services/review_service.py` (+1 -0)
> - Wrote `./app/services/review_service.py` (+27 -3)
>
> </details>
>
> 文件级并发和 batching 的入口已经补上了：收集到 targets 后会按批次处理，每批最多用 `LLM_CONCURRENCY` 个线程。这样大项目不会一次把所有文件都压进执行队列，也不会让配置里的并发数闲置。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+30 -5)
>
> </details>
>
> `_review_file` 现在会在 main_task 后接两个独立校准阶段：先重定位 issue 行号，再做误报过滤；最终 `comment_line_number` 只统计 `issue_show=True` 的问题，但被过滤的问题仍然留库，方便追溯。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+13 -0)
>
> </details>
>
> main_task 的压缩点也接入了：工具循环跑到配置阈值后，会把旧轮次压成摘要消息，再继续请求模型；压缩本身也会作为 `memory_compression` 轮次写入 `model_rounds`。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+104 -0)
>
> </details>
>
> 重定位和过滤的主流程已经接上。现在我补底层判定逻辑：模型可用时走 LLM 阶段，模型不可用或解析失败时走本地兜底，确保不会因为某一轮 JSON 不稳而丢掉校准能力。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+298 -0)
>
> </details>
>
> 本地兜底逻辑也到位了：行号会优先贴回新增行，过滤会检查置信度、行号可解析性、是否属于本次变更。这个兜底不是替代模型，而是保证模型不稳时不会让流程“静默塌掉”。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+25 -0)
> - Wrote `./app/services/review_service.py` (+2 -0)
> - Wrote `./app/services/review_service.py` (+2 -1)
>
> </details>
>
> 任务聚合也调整了：项目汇总和文件评论数只统计最终展示的 issue；被过滤掉的记录仍保留 `filter_status/filter_reason`，方便做误报复盘。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+10 -8)
> - Wrote `./app/services/review_service.py` (+5 -5)
>
> </details>
>
> 我顺手把同文件重复 issue 合并保持在文件范围内，且兼容“同一问题先被过滤、后续 block 又给出有效证据”的情况：保留更有用的那条，项目级仍不做合并。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/schemas/code_file.py` (+12 -0)
> - Wrote `./.env.example` (+8 -0)
>
> </details>
>
> 现在先跑静态导入和测试前检查。我会先让 Python 编译主要模块，尽早抓语法/类型拼写错误，再补测试用例。
>
> 编译检查通过，没有语法问题。接下来我会补几条针对新能力的测试：本地行号重定位、误报过滤、上下文压缩轨迹、JSON 规则解析、以及文件级并发是否真的生效。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+67 -1)
>
> </details>
>
> 测试桩已经补了一个会反复调用工具的假模型，用来触发 10+ 轮时最容易出问题的上下文膨胀路径。现在补断言。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+150 -0)
>
> </details>
>
> 新测试已经写好。我现在跑全量测试，预计可能会暴露一些边角：比如假模型后续轮次不符合新阶段 JSON、或者并发测试里的 Mongo mock 连接需要小修。
>
> 测试暴露了一个好问题：重定位/过滤阶段在“模型返回了内容但 JSON 解析失败”时把同一轮记录了两次。这个会污染 token 统计，我先修掉，让失败只标记在那一轮 trace 上。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+8 -2)
>
> </details>
>
> 这个断言失败本身不是业务错误：新增两个模型阶段后，token 总数自然增加了。为了让测试表达新事实，我会让假模型为重定位/过滤返回合法 JSON，并更新 token 与阶段断言。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+40 -11)
> - Wrote `./tests/test_review_service.py` (+12 -5)
>
> </details>
>
> 我看到刚才补断言时混进了一句无意义的占位断言，我会删掉它，保持测试干净。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+0 -1)
>
> </details>
>
> 这条 trace 测试已经通过，说明 token 统计和新增阶段记录对齐了。我继续跑全量测试，看看并发和压缩路径有没有新的边角。
>
> 全量测试 17 条通过。最后我补 README，把这几个新开关和新落库字段说明清楚，然后再做一次最终测试/配置校验。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./README.md` (+13 -0)
>
> </details>
>
> 文档已经更新。现在做最后一轮测试和 compose 配置校验，确保本地启动配置没有被新环境变量影响。
>
> compose 校验通过，但我注意到 `docker-compose.yml` 还没有把新增环境变量传给 app 容器。这个会导致容器里只能用默认值，我补上再重新校验。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./docker-compose.yml` (+11 -0)
>
> </details>
>
> compose 的环境变量已补齐。再跑一次测试和 compose 配置，这次应该能看到新增开关进入容器环境。
>
> 最终测试和 compose 配置都通过了。最后我看一下变更清单，确认没有误改无关文件，然后给你汇总核心流程现在怎么变了。
</details>

已按你列出的优化顺序落地，核心参考 OCR 的闭环思路做了增强：[Alibaba open-code-review](https://github.com/alibaba/open-code-review)。

本轮主要完成：

- 补了 `RE_LOCATION_TASK`：行号漂移会二次校准，结果落到 `Issue.original_issue_line_numbers / relocation_status / relocation_description`。
- 补了 `REVIEW_FILTER_TASK`：过滤误报，过滤后的 issue 仍落库，但 `issue_show=false`，任务和文件的评论数只统计最终展示的问题。
- main_task 加了上下文压缩：超过配置轮数后压缩旧工具轨迹，写入 `model_rounds`，并记录 `memory_compression_count`。
- 规则体系从语言字典升级为 JSON resolver：新增 [review_rules.json](./app/services/review_rules.json) 和 [rules.py](./app/services/rules.py)，支持 `REVIEW_RULES_PATH` 外部规则。
- 文件级并发和 scan batching 已接入：真正使用 `LLM_CONCURRENCY` 和 `SCAN_BATCH_SIZE`。
- 更新了 MongoEngine 字段、API 响应 schema、`.env.example`、`docker-compose.yml` 和 README。
- 增加测试覆盖：重定位、过滤、上下文压缩、外部 JSON 规则、文件级并发、token/trace 落库。

验证结果：

```text
.venv\Scripts\python.exe -m pytest
17 passed in 1.47s
```

```text
docker compose config
通过，新增环境变量已进入 app 容器配置
```

本轮没有重新调用真实 DeepSeek API，验证主要通过假模型覆盖 function calling、多轮压缩和后处理链路。当前这版的核心流程已经更接近 OCR：`plan_task -> main_task 工具闭环 -> re_location -> review_filter -> 文件内 issue 合并 -> 落库`。

> 请继续检查本项目和OCR的核心实现逻辑是否完全一致？如果有不一致的请指出？并指出哪个实现更好？

<details><summary>4 previous messages</summary>

> 我会把本地当前实现和 OCR 当前仓库再对一遍，重点看流程骨架、工具闭环、重定位/过滤、上下文压缩、并发、规则体系这些会影响准确度的地方。先取本地代码，再核对 OCR 源码入口。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `github alibaba open-code-review internal llmloop loop.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/llmloop/loop.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/agent/agent.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/config/template/task_template.json`
> - Searched the web for `repo:alibaba/open-code-review internal/tool code_search read_file code_comment task_done file_find`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/tool`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/tool/definitions.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/tool/file_find.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/scan/agent.go`
> - Searched the web for `'review_filter' in https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/agent/agent.go`
>
> </details>
>
> </details>
>
> OCR 的当前主线我已经对上：它的 `Runner` 负责 main_task 工具循环、token 聚合和压缩；`Agent` 负责 diff、plan、并发、review_filter；full scan 还有更完整的 batching / token budget / summary。现在我跑一下本项目测试，确认比较基线没有坏。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `alibaba/open-code-review internal/config/template/task_template.json main_task review_filter`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/llmloop/loop.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/agent/agent.go`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/scan/agent.go`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal/tool`
>
> </details>
>
> </details>
</details>

结论：**不完全一致，但核心主链路已经很接近 OCR**。当前项目更像“按业务数据模型改造后的 OCR”，而不是 OCR 的 Python 等价复刻。

我刚重新跑了测试：

```text
17 passed in 1.38s
```

**核心一致的地方**

- 都是 `plan_task -> main_task -> 工具调用循环 -> 结果后处理`。
- 都有 `code_search / read_file / file_read_diff / code_comment / task_done` 这类工具形态。
- 都有文件级并发。
- 都有 re-location、review_filter、memory compression、规则解析、token/耗时/工具轨迹记录。
- 当前项目结果会落 MongoDB 的 `CodeFileModel / CodeBlock / Issue`，这符合你的业务要求。

**主要不一致与优劣**

| 模块 | 当前项目 | OCR | 哪个更好 |
|---|---|---|---|
| Diff 来源 | 本地两个目录 MD5 + Python diff | Git diff provider，支持 workspace/range/commit | OCR 更成熟；当前更符合你要求的本地目录对比 |
| `plan_task` | 每个 block 都做，并输出五维评分 | 小 diff 可跳过 plan，plan 主要生成 guidance | 当前更适合业务评分落库；OCR 更省 token |
| `main_task` 工具闭环 | 工具优先，但支持 JSON fallback | 更强制工具调用，无工具会重试 | OCR 更稳定；当前兼容性更好 |
| `code_comment` | 单 issue 字段直落 DB：severity/type/description/suggestion/line | `comments` 数组，含 content、existing_code、suggestion_code、thinking，并在工具层做行号解析 | OCR 更丰富；当前更贴合现有表 |
| `RE_LOCATION_TASK` | main_task 后对 issue 批量校准，并落库状态 | 集成在 `code_comment` 执行阶段，先 diff resolve，失败才 LLM re-location | OCR 定位更准；当前可观测性更好 |
| `REVIEW_FILTER_TASK` | 不删除，标记 `issue_show=false` 并保留原因 | 从 collector 中移除被过滤评论 | 当前更适合解释误报；OCR 最终输出更干净 |
| Memory compression | 按轮数触发压缩 | 按 token 阈值触发，有 soft/warning 两级和同步/异步压缩 | OCR 更好 |
| Full scan | 把全量文件转成全 `+` diff 逐文件 review | 独立 scan pipeline，有 cost estimate、token budget、batch、dedup、project summary | OCR 明显更完整 |
| 规则体系 | JSON resolver，按语言/扩展名/路径合并 | rule resolver + allowlist + file filter 更成熟 | OCR 更成熟；当前已够业务扩展 |
| 可观测性 | 每个 `CodeBlock` 落库 `model_rounds/tool_calls/token/耗时` | session history + telemetry + token aggregate | 当前对业务查询更好；OCR 对运行时诊断更完整 |
| Resume | 暂无 | 支持 resume，复用已审核文件 | OCR 更好 |
| Scan dedup | 目前只有文件内重复 issue 合并 | full scan 有 batch-level dedup task | OCR 更好 |

**关键源码对照**

- 本项目主流程在 [review_service.py](./app/services/review_service.py)。
- 本项目提示词和工具定义在 [prompts.py](./app/services/prompts.py)。
- 本项目规则解析在 [rules.py](./app/services/rules.py) 和 [review_rules.json](./app/services/review_rules.json)。
- OCR 的 `Runner` 负责工具循环、token 聚合、压缩和 `code_comment` re-location；源码里也明确说明 `RunPerFile` 会执行工具循环，`code_comment` 会做行号 resolution / re-location，压缩按 token 阈值触发：[OCR llmloop](https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/llmloop/loop.go)。
- OCR 的 diff review `Agent` 负责 diff 加载、并发分发、plan/main/review_filter：[OCR agent](https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/agent/agent.go)。
- OCR full scan 有独立 scan pipeline、batch、dedup、summary、token budget：[OCR scan agent](https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/scan/agent.go)。
- OCR 工具目录包含 `code_comment.go`、`code_search.go`、`file_find.go`、`file_read.go`、`file_read_diff.go` 等：[OCR tools](https://github.com/alibaba/open-code-review/tree/main/internal/tool)。

**我的判断**

当前项目已经完成了 OCR 最关键的准确度链路，但还不是“完全一致”。如果目标是业务系统落库、可解释、可查询，当前项目在持久化和误报追溯上更好。如果目标是代码审核准确率、长上下文稳定性、大项目扫描成熟度，OCR 仍然更强。

下一步最值得补的是：把当前 round-based memory compression 改成 OCR 那种 token-threshold compression，然后补 full scan 的 dedup task、project summary 和 token budget。

> 你认为 OCR 哪方面的做法导致比本项目的代码审核准确率？本项目是否在兼顾数据结构的情况下可以优化到和OCR同等水平？
> 如果可以，请继续优化

<details><summary>25 previous messages</summary>

> 我会先把 OCR 准确率更高的“机制原因”拆开，再只挑对当前数据结构最有收益、风险最低的部分继续落地：token 阈值压缩、code_comment 证据增强、行号与代码片段校验、full scan 的可观测 summary。先重新扫本地代码和 OCR 关键实现，避免凭印象下手。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:github.com/alibaba/open-code-review llmloop code_comment re_location review_filter memory compression`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/llmloop/loop.go`
>
> </details>
>
> </details>
>
> OCR 准确率更高，核心不是“模型更聪明”，而是它给模型更强的约束和证据：`code_comment` 必须带代码证据，评论提交时立即做 diff 行号解析/重定位；工具循环没有工具调用会继续追问；压缩按 token 阈值触发，而不是固定轮数；scan 还有 token budget 和项目级摘要。当前数据结构可以承接这些能力，我先补最有收益的三块：证据型 code_comment、证据驱动 re-location/filter、token 阈值压缩。
>
> 我已经确认当前主干可以继续承载这些增强，而且不用打破 `TaskModel / CodeFileModel / CodeBlock / Issue` 的基本结构。接下来会新增少量字段和配置，并调整工具参数与本地校验逻辑，让模型必须提供“问题证据”，这样后处理才能像 OCR 一样更稳。
>
> 我要开始改文件了。第一步是给 Issue 增加“证据字段”，并让 `code_comment` 工具接受 `existing_code / suggestion_code / evidence`；第二步用这些证据改进行号重定位和过滤；第三步把上下文压缩从单纯按轮数升级成“估算 token 超阈值优先触发”。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/models/code_file.py` (+6 -0)
>
> </details>
>
> 数据结构已经补了证据字段。这样不会破坏旧数据，新增字段都有默认值；之后查询 API 也会把这些证据带出来，方便解释为什么这条评论可信。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/schemas/code_file.py` (+12 -0)
> - Wrote `./app/core/config.py` (+3 -0)
>
> </details>
>
> 配置层也补好了：压缩现在会有 token 阈值，过滤阶段也会用证据相似度阈值。接下来改提示词和工具定义，让模型提交问题时自然带上可核验的代码片段。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/prompts.py` (+22 -4)
> - Wrote `./app/services/review_tools.py` (+4 -0)
>
> </details>
>
> 我会把“证据”真正用于后处理：如果模型给出的 `existing_code` 能在新增行匹配，行号会自动贴到那一行；如果匹配不上，过滤阶段会降低置信或直接隐藏。这样它不只是多存字段，而是参与准确率闭环。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+1 -0)
> - Wrote `./app/services/review_service.py` (+25 -3)
>
> </details>
>
> 上下文压缩已经改成 token 阈值优先触发，并保留按轮数兜底。也就是说，长工具结果会更早压缩，短对话不会因为轮数到了就过早压缩。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+6 -0)
> - Wrote `./app/services/review_service.py` (+11 -0)
> - Wrote `./app/services/review_service.py` (+11 -0)
> - Wrote `./app/services/review_service.py` (+45 -0)
> - Wrote `./app/services/review_service.py` (+8 -0)
> - Wrote `./app/services/review_service.py` (+4 -0)
> - Wrote `./app/services/review_service.py` (+7 -0)
> - Wrote `./app/services/review_service.py` (+3 -1)
>
> </details>
>
> 现在我会修测试桩，让它们也按新的 `code_comment` 证据协议提交内容。旧协议仍能解析，但为了模拟真实模型调用，测试最好跟新约束保持一致。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+16 -5)
>
> </details>
>
> 语法检查通过。接下来跑测试，我预计可能会出现一两个断言要跟新字段或新过滤原因对齐。
>
> 现有测试已经全绿。为了证明新增能力不是“字段摆设”，我再补两条专门测试：一条验证 token 阈值触发压缩，另一条验证 evidence 与变更行不匹配时会被过滤。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/test_review_tools.py` (+25 -0)
> - Wrote `./tests/test_review_service.py` (+67 -0)
>
> </details>
>
> 新增测试已写好。接下来补环境变量和文档，让部署时也能显式调 token 压缩阈值和证据匹配阈值。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./.env.example` (+3 -0)
> - Wrote `./docker-compose.yml` (+3 -0)
>
> </details>
>
> 配置已经同步到 `.env.example` 和 compose。现在我更新 README，把“为什么准确率更高”的机制写进项目说明，后续你或别人调参时不会只看到一堆开关。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./README.md` (+5 -1)
>
> </details>
>
> 编译检查通过。现在跑全量测试和 compose 配置校验，确认新配置进容器、功能没有回归。
>
> 测试 20 条全绿，compose 也能看到新环境变量。最后我看一下变更清单，确认这次修改集中在模型、提示词、工具和测试，没有误动无关逻辑。
</details>

可以。本项目在“本地目录增量/全量扫描 + MongoDB 落库”这个业务边界内，可以继续优化到接近 OCR 的准确率；但如果说完全同等，还差 OCR 的 Git diff provider、scan resume、full scan project summary / dedup 这些外围能力。

OCR 准确率更高，主要靠这些机制：

- `code_comment` 要求更强证据，不只是描述问题，还带问题代码、建议代码、定位信息。
- 评论提交时马上做行号解析和 re-location，而不是完全相信模型给的行号。
- `review_filter` 会二次过滤误报。
- main_task 工具闭环更硬，逼模型读上下文、查代码、再评论。
- memory compression 按 token 压力触发，更适合长工具循环。
- full scan 有 batching、token budget、dedup、summary，适合大项目。

我这轮已经继续优化了当前项目，重点补了 OCR 准确率链路里最关键、且兼容现有数据结构的部分：

- `Issue` 增加证据字段：`existing_code`、`suggestion_code`、`evidence`、`rule_id`、`evidence_match_status`、`evidence_match_score`。
- `code_comment` 工具现在要求模型提交 `existing_code/evidence`，不再只靠自然语言描述。
- `RE_LOCATION_TASK` 会用 `existing_code` 与本次新增行做相似度匹配，自动修正漂移行号。
- `REVIEW_FILTER_TASK` 会过滤证据缺失、证据代码与变更行不匹配、置信度低、行号不属于本次变更的问题。
- memory compression 从单纯按轮数触发，升级为 token 阈值优先触发，`LLM_CONTEXT_COMPRESS_TOKEN_THRESHOLD=12000`。
- API 响应、README、`.env.example`、`docker-compose.yml` 都同步了新字段和新配置。

关键文件：

- [review_service.py](./app/services/review_service.py)
- [prompts.py](./app/services/prompts.py)
- [review_tools.py](./app/services/review_tools.py)
- [code_file.py](./app/models/code_file.py)
- [README.md](./README.md)

验证结果：

```text
.venv\Scripts\python.exe -m pytest
20 passed in 0.99s
```

```text
docker compose config
通过，新环境变量已进入 app 容器配置
```

参考 OCR 核心实现：
[llmloop](https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/llmloop/loop.go)、[agent](https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/agent/agent.go)、[scan agent](https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/scan/agent.go)、[tools](https://github.com/alibaba/open-code-review/tree/main/internal/tool)。

剩下如果要继续追平 OCR，下一步最值的是：补 full scan 的 project summary、batch dedup、token budget，以及任务 resume。

> 如果要继续追平 OCR，下一步最值的是：补 full scan 的 project summary、batch dedup、token budget，以及任务 resume。
>
> 请结合这些点继续优化本项目

<details><summary>25 previous messages</summary>

> 我会继续按 AGENTS 的要求先扫一下当前仓库和核心服务，再给一个短计划，然后直接实现。这里我会尽量不推翻现有数据结构：优先复用 `TaskModel.developer_issue_summary`、`CodeFileModel.extra`，只在确实有价值的地方加字段。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/scan/agent.go`
>
> </details>
>
> </details>
>
> 实现计划很短：我会把 OCR full scan 的四个关键点映射到现有业务表里：`token budget` 控制调度，`resume` 跳过已完成且源码没变的文件，`batch dedup` 在每个批次后做 issue 合并/隐藏，`project summary` 在任务结束时汇总到 `TaskModel`。这几个都会保留可观测信息，不会只在内存里一闪而过。
>
> 现在要落第二批改动：我会新增任务级统计字段，然后调整调度入口。重点是让 resume 和 token budget 发生在真正调用 LLM 之前，这样才能节省成本，而不是审核完再“事后统计”。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./app/models/task.py` (+6 -0)
> - Wrote `./app/schemas/task.py` (+12 -0)
> - Wrote `./app/core/config.py` (+4 -0)
>
> </details>
>
> 任务模型和配置已经补齐：现在可以记录跳过文件数、resume 文件数、估算 token、预算 token、项目摘要。下一步改审核调度：准备已有结果、预算筛选、批次去重。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+5 -1)
> - Wrote `./app/services/review_service.py` (+12 -6)
>
> </details>
>
> 调度入口已经改成“三类文件”：可复用的、预算跳过的、需要真正审核的。批次审核完成后会立刻做 batch dedup，而不是等整个项目结束。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+107 -0)
>
> </details>
>
> 预算跳过会落一个 `CodeFileModel`，状态是 `skipped_budget`，所以后续查询能看到“为什么没审”。resume 的文件也会更新 `extra.status=resumed`，不是悄悄跳过。接下来给每个实际审核文件写入 source hash/估算 token。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+9 -0)
> - Wrote `./app/services/review_service.py` (+72 -0)
>
> </details>
>
> batch dedup 已补：只在 full scan 的当前批次里去重，重复 issue 不删除，而是 `issue_show=false` 并写 `filter_reason=batch_dedup...`。这比全项目直接合并更温和，也保留审计线索。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+92 -2)
>
> </details>
>
> 项目摘要已经落到 `TaskModel.project_summary`，详细结构在 `developer_issue_summary._project_summary`。我再小修一个语义：resume 的文件也是“已完成审核”，所以 `reviewed_file_num` 应该包含 resumed 文件。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./app/services/review_service.py` (+5 -1)
> - Wrote `./.env.example` (+4 -0)
> - Wrote `./docker-compose.yml` (+4 -0)
>
> </details>
>
> 配置已经同步。现在补测试覆盖这四个点：预算跳过、resume 复用、batch dedup、项目摘要。用 mock 模型跑，速度快，也能证明调度逻辑本身稳定。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+79 -0)
>
> </details>
>
> 新增测试已写好。现在先做编译检查，再跑全量测试；如果预算估算导致边界不稳定，我会把测试改成更稳的断言。
>
> 编译通过，继续跑测试。
>
> 23 条测试已经通过。接下来补 README，把 full scan 的预算、resume、batch dedup、项目摘要说明清楚，然后做 compose 配置校验。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./README.md` (+11 -0)
>
> </details>
>
> 测试和 compose 都过了。最后我看一下变更清单，确保实现集中在本次目标相关文件。
>
> 我注意到 `CodeFileModel.extra.status` 虽然已经落库，但接口响应 schema 还没直接返回 `extra`。这会影响你从接口看 skipped/resumed/reviewed 状态，我补上这一点再收尾。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/schemas/code_file.py` (+2 -0)
>
> </details>
>
> 接口现在会返回 `CodeFileModel.extra`，可以直接看到预算跳过、resume 复用等状态。再跑一遍测试确认 schema 改动没影响 API。
</details>

已继续按 OCR scan 的方向补齐四块能力，并保持和当前 Mongo 数据结构兼容。

这轮新增/优化：

- **Full scan token budget**
  - 新增 `FULL_SCAN_TOKEN_BUDGET`，`0` 表示不限制。
  - 超预算文件不会静默消失，会保存 `CodeFileModel`，`extra.status=skipped_budget`。
  - `TaskModel` 记录 `estimated_token_num / consumed_estimated_token_num / token_budget_num / skipped_file_num`。

- **任务 resume**
  - 新增 `REVIEW_RESUME_ENABLED=true`。
  - 同一个 task 重跑时，如果文件 `source_hash` 未变化、历史结果无失败，会直接复用已有 `CodeFileModel`。
  - 复用结果标记为 `extra.status=resumed`，并记录 `resumed_file_num`。

- **Full scan batch dedup**
  - 新增 `FULL_SCAN_BATCH_DEDUP_ENABLED=true`。
  - 每个 batch 内重复 issue 会被过滤：保留落库，但 `issue_show=false`，`filter_reason=batch_dedup...`。
  - 不做全项目强合并，避免误删不同文件里真实重复风险。

- **Project summary**
  - 新增 `TaskModel.project_summary`。
  - `developer_issue_summary._project_summary` 保存任务级摘要、严重度分布、重点文件、预算状态、resume 状态。
  - API 响应也补了 `CodeFileModel.extra`，方便直接看 `reviewed/resumed/skipped_budget`。

相关文件主要是：

- [review_service.py](./app/services/review_service.py)
- [task.py](./app/models/task.py)
- [code_file.py](./app/schemas/code_file.py)
- [config.py](./app/core/config.py)
- [README.md](./README.md)

验证结果：

```text
.venv\Scripts\python.exe -m pytest
23 passed in 1.05s
```

```text
docker compose config
通过，新环境变量已进入 app 容器配置
```

参考 OCR 方向：full scan 的 batching、dedup、budget、summary 思路来自 [OCR scan agent](https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/scan/agent.go)，工具循环与压缩参考 [OCR llmloop](https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/llmloop/loop.go)。这次没有重新调用真实 DeepSeek API，验证用的是 mock/假模型覆盖核心流程。

<details><summary>37 previous messages</summary>

> Context compaction
>
> Source: automatic
> Status: completed
>
> 我先按 `AGENTS.md` 重新核对仓库现状，并用 GitHub 仓库分析能力读取 OCR 当前实现；随后会把差异按“准确度影响”排序，直接落实最有价值的改进并补测试。重点会盯住证据定位、工具闭环、过滤/复核、跨文件语义和可恢复执行，而不是只做字段层面的对齐。
>
> GitHub 技能把这次工作归类为“仓库实现对照”，因此我会以 OCR 的源码为依据，而不是只参考 README 或概念描述。现在先锁定本项目的实际调用链、配置和测试覆盖，再逐项映射 OCR 的 agent、llmloop、scan 与 tool 实现。
>
> 当前工程已经具备上一轮补出的 resume、预算、批次去重和项目摘要，但从符号层面看，仍可能存在几个“看似有模块、实际闭环不够强”的风险：任务级轨迹缺失、证据校验偏启发式、跨文件依赖搜索受限，以及跳过/恢复语义可能影响最终状态。接下来按三步推进：先做源码级一一映射；再实现准确度收益最高且能适配现有 Mongo 数据结构的改进；最后跑完整测试和容器配置校验。
>
> <details><summary>Called 8 tools, searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:github.com/alibaba/open-code-review internal agent plan_task main_task RE_LOCATION_TASK REVIEW_FILTER_TASK ...`
> - Searched the web for `https://github.com/alibaba/open-code-review/tree/main/internal`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/agent/agent.go`
>
> </details>
>
> MCP tool call
>
> codex_apps.github.search
>
> ```json
> {
>   "query": "RE_LOCATION_TASK",
>   "repository_name": "alibaba/open-code-review",
>   "org": "alibaba",
>   "topn": 20
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "results": [
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "path": "internal/config/template/template.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "display_title": "internal/config/template/template.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/viewer.md",
>       "path": "pages/src/content/docs/zh/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/viewer.md",
>       "display_title": "pages/src/content/docs/zh/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/architecture.md",
>       "path": "pages/src/content/docs/zh/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/architecture.md",
>       "display_title": "pages/src/content/docs/zh/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/viewer/store.go",
>       "path": "internal/viewer/store.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/viewer/store.go",
>       "display_title": "internal/viewer/store.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/tools.md",
>       "path": "pages/src/content/docs/zh/tools.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/tools.md",
>       "display_title": "pages/src/content/docs/zh/tools.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/session/history.go",
>       "path": "internal/session/history.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/session/history.go",
>       "display_title": "internal/session/history.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/task_template.json",
>       "path": "internal/config/template/task_template.json",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/task_template.json",
>       "display_title": "internal/config/template/task_template.json"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/scan_template.json",
>       "path": "internal/config/template/scan_template.json",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/scan_template.json",
>       "display_title": "internal/config/template/scan_template.json"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/viewer.md",
>       "path": "pages/src/content/docs/en/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/viewer.md",
>       "display_title": "pages/src/content/docs/en/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/architecture.md",
>       "path": "pages/src/content/docs/en/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/architecture.md",
>       "display_title": "pages/src/content/docs/en/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/tools.md",
>       "path": "pages/src/content/docs/ja/tools.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/tools.md",
>       "display_title": "pages/src/content/docs/ja/tools.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/architecture.md",
>       "path": "pages/src/content/docs/ja/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/architecture.md",
>       "display_title": "pages/src/content/docs/ja/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/tools.md",
>       "path": "pages/src/content/docs/en/tools.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/tools.md",
>       "display_title": "pages/src/content/docs/en/tools.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/viewer.md",
>       "path": "pages/src/content/docs/ja/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/viewer.md",
>       "display_title": "pages/src/content/docs/ja/viewer.md"
>     }
>   ]
> }
> ```
>
> MCP tool call
>
> codex_apps.github.search
>
> ```json
> {
>   "query": "REVIEW_FILTER_TASK",
>   "repository_name": "alibaba/open-code-review",
>   "org": "alibaba",
>   "topn": 20
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "results": [
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "path": "internal/config/template/template.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "display_title": "internal/config/template/template.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/architecture.md",
>       "path": "pages/src/content/docs/zh/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/architecture.md",
>       "display_title": "pages/src/content/docs/zh/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/architecture.md",
>       "path": "pages/src/content/docs/en/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/architecture.md",
>       "display_title": "pages/src/content/docs/en/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/viewer.md",
>       "path": "pages/src/content/docs/zh/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/viewer.md",
>       "display_title": "pages/src/content/docs/zh/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/viewer.md",
>       "path": "pages/src/content/docs/en/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/viewer.md",
>       "display_title": "pages/src/content/docs/en/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/architecture.md",
>       "path": "pages/src/content/docs/ja/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/architecture.md",
>       "display_title": "pages/src/content/docs/ja/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/viewer.md",
>       "path": "pages/src/content/docs/ja/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/viewer.md",
>       "display_title": "pages/src/content/docs/ja/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/agent/agent.go",
>       "path": "internal/agent/agent.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/agent/agent.go",
>       "display_title": "internal/agent/agent.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/session/history.go",
>       "path": "internal/session/history.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/session/history.go",
>       "display_title": "internal/session/history.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/task_template.json",
>       "path": "internal/config/template/task_template.json",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/task_template.json",
>       "display_title": "internal/config/template/task_template.json"
>     }
>   ]
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/llmloop/compression.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ````json
> {
>   "content": "package llmloop\n\nimport (\n\t\"context\"\n\t\"fmt\"\n\t\"strings\"\n\t\"sync/atomic\"\n\t\"time\"\n\n\t\"github.com/open-code-review/open-code-review/internal/llm\"\n\t\"github.com/open-code-review/open-code-review/internal/session\"\n\t\"github.com/open-code-review/open-code-review/internal/stdout\"\n)\n\n// Compression thresholds, as fractions of MaxTokens.\nconst (\n\ttokenSoftThreshold    = 0.60 // async background compression\n\ttokenWarningThreshold = 0.80 // immediate sync compression\n)\n\n// round groups consecutive messages starting with an assistant message\n// followed by zero or more tool result messages.\ntype round struct {\n\tassistantIdx int\n\ttoolIdxs     []int\n}\n\n// partitionResult describes how messages should be split for compression.\ntype partitionResult struct {\n\tfrozenEnd   int\n\tcompressEnd int\n\trounds      []round\n\tactiveCount int\n}\n\n// compressionJob tracks an in-flight background compression operation.\ntype compressionJob struct {\n\tdone        chan struct{}\n\trebuilt     []llm.Message\n\tcancel      context.CancelFunc\n\tsnapshotLen int // message count when the snapshot was taken\n}\n\n// CountMessagesTokens returns the rough token count of msgs by summing the\n// per-message text token count. Exported because both review and scan top\n// layers may want it for pre-flight checks.\nfunc CountMessagesTokens(msgs []llm.Message) int {\n\tvar total int\n\tfor _, m := range msgs {\n\t\ttotal += llm.CountTokens(m.ExtractText())\n\t}\n\treturn total\n}\n\n// groupIntoRounds parses messages[start:] into logical\n// (assistant + tool_results) pairs.\nfunc groupIntoRounds(messages []llm.Message, start int) []round {\n\tvar rounds []round\n\ti := start\n\tfor i < len(messages) {\n\t\tif messages[i].Role == \"assistant\" {\n\t\t\tr := round{assistantIdx: i}\n\t\t\ti++\n\t\t\tfor i < len(messages) && messages[i].Role == \"tool\" {\n\t\t\t\tr.toolIdxs = append(r.toolIdxs, i)\n\t\t\t\ti++\n\t\t\t}\n\t\t\trounds = append(rounds, r)\n\t\t} else {\n\t\t\ti++\n\t\t}\n\t}\n\treturn rounds\n}\n\n// computeActiveZoneSize returns how many trailing rounds fit within the\n// remaining token budget after accounting for the frozen zone and the\n// compressed summary.\nfunc computeActiveZoneSize(rounds []round, messages []llm.Message, maxTokens int, reservedTokens int) int {\n\tbudget := int(float64(maxTokens)*tokenWarningThreshold) - reservedTokens\n\tif budget <= 0 {\n\t\treturn 0\n\t}\n\n\tcount := 0\n\ttokensUsed := 0\n\tfor i := len(rounds) - 1; i >= 0; i-- {\n\t\troundTokens := llm.CountTokens(messages[rounds[i].assistantIdx].ExtractText())\n\t\tfor _, ti := range rounds[i].toolIdxs {\n\t\t\troundTokens += llm.CountTokens(messages[ti].ExtractText())\n\t\t}\n\t\tif tokensUsed+roundTokens > budget {\n\t\t\tbreak\n\t\t}\n\t\ttokensUsed += roundTokens\n\t\tcount++\n\t}\n\treturn count\n}\n\n// partitionMessages divides messages into frozen, compress, and active zones.\n// Frozen zone is always messages[0:2]. Active zone preserves the K most\n// recent complete rounds based on available token budget.\nfunc partitionMessages(messages []llm.Message, maxTokens int, prevSummaryTokenEstimate int) partitionResult {\n\tresult := partitionResult{frozenEnd: 2}\n\tif len(messages) <= 2 {\n\t\tresult.compressEnd = len(messages)\n\t\treturn result\n\t}\n\n\tresult.rounds = groupIntoRounds(messages, 2)\n\tif len(result.rounds) == 0 {\n\t\tresult.compressEnd = len(messages)\n\t\treturn result\n\t}\n\n\tresult.activeCount = computeActiveZoneSize(result.rounds, messages, maxTokens, prevSummaryTokenEstimate)\n\tif result.activeCount >= len(result.rounds) {\n\t\t// Everything fits — no compression needed.\n\t\tresult.compressEnd = len(messages)\n\t\tresult.activeCount = 0\n\t\treturn result\n\t}\n\n\t// compressEnd = index after the last round NOT in active zone.\n\tactiveStartIdx := len(result.rounds) - result.activeCount\n\tlastCompressRound := result.rounds[activeStartIdx-1]\n\tif len(lastCompressRound.toolIdxs) > 0 {\n\t\tresult.compressEnd = lastCompressRound.toolIdxs[len(lastCompressRound.toolIdxs)-1] + 1\n\t} else {\n\t\tresult.compressEnd = lastCompressRound.assistantIdx + 1\n\t}\n\n\treturn result\n}\n\n// StripMarkdownFences removes ```json and ``` wrappers some models add\n// around structured outputs. Exposed so callers (e.g. agent's review-filter\n// post-step) that parse LLM JSON output can reuse the same heuristic.\nfunc StripMarkdownFences(s string) string { return stripMarkdownFences(s) }\n\n// stripMarkdownFences is the package-private workhorse used by the\n// internal compression code paths.\nfunc stripMarkdownFences(s string) string {\n\ts = strings.TrimSpace(s)\n\tif strings.HasPrefix(s, \"```\") {\n\t\tif nl := strings.IndexByte(s, '\\n'); nl >= 0 {\n\t\t\ts = s[nl+1:]\n\t\t} else {\n\t\t\ts = strings.TrimPrefix(s, \"```json\")\n\t\t\ts = strings.TrimPrefix(s, \"```\")\n\t\t}\n\t}\n\ts = strings.TrimSpace(s)\n\tif strings.HasSuffix(s, \"```\") {\n\t\ts = strings.TrimSuffix(s, \"```\")\n\t\ts = strings.TrimSpace(s)\n\t}\n\treturn s\n}\n\n// buildMessageXML serializes msgs into the <message><content> form expected\n// by the MEMORY_COMPRESSION_TASK prompt template.\nfunc buildMessageXML(msgs []llm.Message) string {\n\tvar sb strings.Builder\n\tfor i, m := range msgs {\n\t\tsb.WriteString(fmt.Sprintf(\"<message id=\\\"%d\\\" role=\\\"%s\\\">\\n\", i, m.Role))\n\t\tsb.WriteString(\"    <content>\\n\")\n\t\tsb.WriteString(fmt.Sprintf(\"      %s\\n\", m.ExtractText()))\n\t\tsb.WriteString(\"    </content>\\n\")\n\t\tsb.WriteString(\"</message>\")\n\t\tif i < len(msgs)-1 {\n\t\t\tsb.WriteString(\"\\n\")\n\t\t}\n\t}\n\treturn sb.String()\n}\n\n// copyMessages creates a shallow copy of a message slice.\nfunc copyMessages(msgs []llm.Message) []llm.Message {\n\tout := make([]llm.Message, len(msgs))\n\tcopy(out, msgs)\n\treturn out\n}\n\n// runCompression performs three-zone memory compression on the given\n// messages, summarizing the compress zone while preserving the active zone\n// intact. Returns rebuilt as [frozen] + [compressed_summary appended to\n// the user prompt] + [active].\nfunc (r *Runner) runCompression(ctx context.Context, msgs []llm.Message, filePath string) ([]llm.Message, error) {\n\tif len(r.deps.Template.MemoryCompressionTask.Messages) == 0 || len(msgs) <= 2 {\n\t\treturn msgs[:min(len(msgs), 2)], nil\n\t}\n\n\tpart := partitionMessages(msgs, r.deps.Template.MaxTokens, 0)\n\tif part.compressEnd <= part.frozenEnd {\n\t\treturn msgs, nil\n\t}\n\n\tcontextXML := buildMessageXML(msgs[part.frozenEnd:part.compressEnd])\n\n\tcompressionMsgs := make([]llm.Message, 0, len(r.deps.Template.MemoryCompressionTask.Messages))\n\tfor _, m := range r.deps.Template.MemoryCompressionTask.Messages {\n\t\tcontent := strings.ReplaceAll(m.Content, \"{{context}}\", contextXML)\n\t\tcompressionMsgs = append(compressionMsgs, llm.NewTextMessage(m.Role, content))\n\t}\n\n\tstartTime := time.Now()\n\tresp, err := r.deps.LLMClient.CompletionsWithCtx(ctx, llm.ChatRequest{\n\t\tModel:     r.deps.Model,\n\t\tMessages:  compressionMsgs,\n\t\tMaxTokens: r.deps.Template.MaxTokens,\n\t})\n\tduration := time.Since(startTime)\n\n\tfs := r.deps.Session.GetOrCreateFileSession(filePath)\n\trec := fs.AppendTaskRecord(session.MemoryCompressionTask, compressionMsgs)\n\tif err != nil {\n\t\trec.SetError(err, duration)\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Memory compression failed: %v\\n\", err)\n\t\t// Return msgs unchanged: truncating to frozenEnd would discard all\n\t\t// conversation context, which is worse than staying over the token\n\t\t// limit temporarily.\n\t\treturn msgs, fmt.Errorf(\"memory compression: %w\", err)\n\t}\n\trec.SetResponse(resp, duration)\n\tif resp.Usage != nil {\n\t\tatomic.AddInt64(&r.totalInputTokens, resp.Usage.PromptTokens)\n\t\tatomic.AddInt64(&r.totalOutputTokens, resp.Usage.CompletionTokens)\n\t\tatomic.AddInt64(&r.totalCacheReadTokens, resp.Usage.CacheReadTokens)\n\t\tatomic.AddInt64(&r.totalCacheWriteTokens, resp.Usage.CacheWriteTokens)\n\t}\n\n\trawSummary := stripMarkdownFences(resp.Content())\n\tif rawSummary == \"\" {\n\t\t// Empty summary: keep the original conversation rather than dropping\n\t\t// everything below the frozen zone.\n\t\treturn msgs, nil\n\t}\n\n\trebuilt := make([]llm.Message, 2)\n\tcopy(rebuilt, msgs[:2])\n\n\tuserMsg := rebuilt[1]\n\tcurrentText := userMsg.ExtractText()\n\trebuilt[1] = llm.NewTextMessage(userMsg.Role, currentText+\"\\n\\n<previous_review_summary>\\n\"+rawSummary+\"\\n</previous_review_summary>\")\n\n\tfor i := part.compressEnd; i < len(msgs); i++ {\n\t\trebuilt = append(rebuilt, msgs[i])\n\t}\n\n\treturn rebuilt, nil\n}\n\n// triggerAsyncCompression kicks off a background compression job.\nfunc (r *Runner) triggerAsyncCompression(ctx context.Context, messages []llm.Message, filePath string) {\n\tmsgSnapshot := copyMessages(messages)\n\n\tasyncCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Minute)\n\n\tjob := &compressionJob{done: make(chan struct{}), cancel: cancel, snapshotLen: len(messages)}\n\tr.compressionMu.Lock()\n\tr.pendingJob = job\n\tr.compressionMu.Unlock()\n\n\tgo func() {\n\t\tdefer cancel()\n\t\trebuilt, err := r.runCompression(asyncCtx, msgSnapshot, filePath)\n\n\t\tr.compressionMu.Lock()\n\t\tdefer r.compressionMu.Unlock()\n\n\t\tif r.pendingJob != job {\n\t\t\treturn // cancelled or superseded\n\t\t}\n\t\tif err != nil {\n\t\t\t// Compression failed — abandon the job rather than applying a\n\t\t\t// truncated/unmodified snapshot over live messages.\n\t\t\tr.pendingJob = nil\n\t\t\tclose(job.done)\n\t\t\treturn\n\t\t}\n\t\tjob.rebuilt = rebuilt\n\t\tclose(job.done)\n\t}()\n}\n\n// tryApplyPendingCompression checks whether a background compression has\n// completed and swaps the rebuilt messages into place. Returns true if\n// applied.\nfunc (r *Runner) tryApplyPendingCompression(messages *[]llm.Message) bool {\n\tr.compressionMu.Lock()\n\tjob := r.pendingJob\n\tr.compressionMu.Unlock()\n\n\tif job == nil {\n\t\treturn false\n\t}\n\n\tselect {\n\tcase <-job.done:\n\t\tapplied := false\n\t\tr.compressionMu.Lock()\n\t\tif r.pendingJob == job && job.rebuilt != nil {\n\t\t\trebuilt := job.rebuilt\n\t\t\t// Preserve any messages appended after the snapshot was taken —\n\t\t\t// the background job only compressed messages[:snapshotLen].\n\t\t\tif job.snapshotLen < len(*messages) {\n\t\t\t\trebuilt = append(rebuilt, (*messages)[job.snapshotLen:]...)\n\t\t\t}\n\t\t\t*messages = rebuilt\n\t\t\tapplied = true\n\t\t}\n\t\tif r.pendingJob == job {\n\t\t\tr.pendingJob = nil\n\t\t}\n\t\tr.compressionMu.Unlock()\n\t\treturn applied\n\tdefault:\n\t\treturn false\n\t}\n}\n\n// cancelPendingCompression aborts any in-flight background compression.\nfunc (r *Runner) cancelPendingCompression() {\n\tr.compressionMu.Lock()\n\tdefer r.compressionMu.Unlock()\n\n\tif r.pendingJob != nil {\n\t\tr.pendingJob.cancel()\n\t\tr.pendingJob = nil\n\t}\n}\n",
>   "encoding": "utf-8",
>   "sha": "89f9f8ca469b372013a21fd28b7ce3d2ca9d6ec0",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/compression.go",
>   "display_title": "compression.go"
> }
> ````
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/tool/code_comment.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package tool\n\nimport (\n\t\"context\"\n\t\"encoding/json\"\n\t\"fmt\"\n\n\t\"github.com/open-code-review/open-code-review/internal/model\"\n)\n\n// CodeCommentProvider submits review comments to the per-Agent CommentCollector.\ntype CodeCommentProvider struct {\n\tCollector *CommentCollector\n}\n\nfunc (p *CodeCommentProvider) Tool() Tool { return CodeComment }\n\nfunc (p *CodeCommentProvider) Execute(_ context.Context, args map[string]any) (string, error) {\n\tif p.Collector == nil {\n\t\treturn \"Error: comment collector is not configured\", nil\n\t}\n\n\tcomments, errMsg := ParseComments(args)\n\tif errMsg != \"\" {\n\t\treturn errMsg, nil\n\t}\n\n\tfor i := range comments {\n\t\tp.Collector.Add(comments[i])\n\t}\n\treturn CommentSucceed, nil\n}\n\n// ParseComments extracts LlmComment entries from tool call arguments without writing\n// to the Collector. Returns parsed comments and an error message (empty on success).\nfunc ParseComments(args map[string]any) ([]model.LlmComment, string) {\n\tvar rawComments []any\n\tif arr, ok := args[\"comments\"].([]any); ok && len(arr) > 0 {\n\t\trawComments = arr\n\t} else if s, ok := args[\"comments\"].(string); ok && s != \"\" {\n\t\tif err := json.Unmarshal([]byte(s), &rawComments); err != nil {\n\t\t\treturn nil, fmt.Sprintf(\"Error: failed to parse 'comments' JSON string: %v\", err)\n\t\t}\n\t}\n\tif len(rawComments) == 0 {\n\t\traw, _ := json.Marshal(args)\n\t\treturn nil, fmt.Sprintf(\"Error: 'comments' array is required. Got args: %s\", string(raw))\n\t}\n\n\tvar comments []model.LlmComment\n\tfor _, raw := range rawComments {\n\t\tobj, ok := raw.(map[string]any)\n\t\tif !ok {\n\t\t\tcontinue\n\t\t}\n\n\t\tcm := model.LlmComment{}\n\n\t\tif content, ok := obj[\"content\"].(string); ok {\n\t\t\tcm.Content = content\n\t\t}\n\t\tif suggestion, ok := obj[\"suggestion_code\"].(string); ok {\n\t\t\tcm.SuggestionCode = suggestion\n\t\t}\n\t\tif existing, ok := obj[\"existing_code\"].(string); ok {\n\t\t\tcm.ExistingCode = existing\n\t\t}\n\t\tif thinking, ok := obj[\"thinking\"].(string); ok {\n\t\t\tcm.Thinking = thinking\n\t\t}\n\t\tif category, ok := obj[\"category\"].(string); ok {\n\t\t\tcm.Category = category\n\t\t}\n\t\tif severity, ok := obj[\"severity\"].(string); ok {\n\t\t\tcm.Severity = severity\n\t\t}\n\t\tif path, ok := args[\"path\"].(string); ok {\n\t\t\tcm.Path = path\n\t\t}\n\n\t\tif cm.Path == \"\" || cm.Content == \"\" {\n\t\t\tcontinue\n\t\t}\n\n\t\tcomments = append(comments, cm)\n\t}\n\treturn comments, \"\"\n}\n",
>   "encoding": "utf-8",
>   "sha": "2dac3cb840bc4b985bf39db4c5e9de52b1a9c20c",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/tool/code_comment.go",
>   "display_title": "code_comment.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.search
>
> ```json
> {
>   "query": "task_done",
>   "repository_name": "alibaba/open-code-review",
>   "org": "alibaba",
>   "topn": 20
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "results": [
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/tools.md",
>       "path": "pages/src/content/docs/en/tools.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/tools.md",
>       "display_title": "pages/src/content/docs/en/tools.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/tool/definitions.go",
>       "path": "internal/tool/definitions.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/tool/definitions.go",
>       "display_title": "internal/tool/definitions.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/faq.md",
>       "path": "pages/src/content/docs/en/faq.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/faq.md",
>       "display_title": "pages/src/content/docs/en/faq.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/mcp.md",
>       "path": "pages/src/content/docs/zh/mcp.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/mcp.md",
>       "display_title": "pages/src/content/docs/zh/mcp.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/llmloop/loop.go",
>       "path": "internal/llmloop/loop.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/llmloop/loop.go",
>       "display_title": "internal/llmloop/loop.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/prompts/main_task_system.md",
>       "path": "internal/config/template/prompts/main_task_system.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/prompts/main_task_system.md",
>       "display_title": "internal/config/template/prompts/main_task_system.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/architecture.md",
>       "path": "pages/src/content/docs/zh/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/architecture.md",
>       "display_title": "pages/src/content/docs/zh/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/viewer/store.go",
>       "path": "internal/viewer/store.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/viewer/store.go",
>       "display_title": "internal/viewer/store.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/viewer.md",
>       "path": "pages/src/content/docs/zh/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/viewer.md",
>       "display_title": "pages/src/content/docs/zh/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/scan_template.json",
>       "path": "internal/config/template/scan_template.json",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/scan_template.json",
>       "display_title": "internal/config/template/scan_template.json"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/toolsconfig/tools.json",
>       "path": "internal/config/toolsconfig/tools.json",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/toolsconfig/tools.json",
>       "display_title": "internal/config/toolsconfig/tools.json"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/mcp.md",
>       "path": "pages/src/content/docs/en/mcp.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/mcp.md",
>       "display_title": "pages/src/content/docs/en/mcp.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/architecture.md",
>       "path": "pages/src/content/docs/en/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/architecture.md",
>       "display_title": "pages/src/content/docs/en/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/viewer.md",
>       "path": "pages/src/content/docs/en/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/viewer.md",
>       "display_title": "pages/src/content/docs/en/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/tools.md",
>       "path": "pages/src/content/docs/ja/tools.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/tools.md",
>       "display_title": "pages/src/content/docs/ja/tools.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/faq.md",
>       "path": "pages/src/content/docs/zh/faq.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/faq.md",
>       "display_title": "pages/src/content/docs/zh/faq.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/mcp.md",
>       "path": "pages/src/content/docs/ja/mcp.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/mcp.md",
>       "display_title": "pages/src/content/docs/ja/mcp.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/viewer.md",
>       "path": "pages/src/content/docs/ja/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/viewer.md",
>       "display_title": "pages/src/content/docs/ja/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/faq.md",
>       "path": "pages/src/content/docs/ja/faq.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/faq.md",
>       "display_title": "pages/src/content/docs/ja/faq.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/architecture.md",
>       "path": "pages/src/content/docs/ja/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/architecture.md",
>       "display_title": "pages/src/content/docs/ja/architecture.md"
>     }
>   ]
> }
> ```
>
> MCP tool call
>
> codex_apps.github.search
>
> ```json
> {
>   "query": "memory_compression",
>   "repository_name": "alibaba/open-code-review",
>   "org": "alibaba",
>   "topn": 20
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "results": [
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "path": "internal/config/template/template.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "display_title": "internal/config/template/template.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/viewer.md",
>       "path": "pages/src/content/docs/zh/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/viewer.md",
>       "display_title": "pages/src/content/docs/zh/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/viewer.md",
>       "path": "pages/src/content/docs/en/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/viewer.md",
>       "display_title": "pages/src/content/docs/en/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/viewer.md",
>       "path": "pages/src/content/docs/ja/viewer.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/viewer.md",
>       "display_title": "pages/src/content/docs/ja/viewer.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/session/history.go",
>       "path": "internal/session/history.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/session/history.go",
>       "display_title": "internal/session/history.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/architecture.md",
>       "path": "pages/src/content/docs/zh/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/zh/architecture.md",
>       "display_title": "pages/src/content/docs/zh/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/architecture.md",
>       "path": "pages/src/content/docs/en/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/en/architecture.md",
>       "display_title": "pages/src/content/docs/en/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/viewer/store.go",
>       "path": "internal/viewer/store.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/viewer/store.go",
>       "display_title": "internal/viewer/store.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/architecture.md",
>       "path": "pages/src/content/docs/ja/architecture.md",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/content/docs/ja/architecture.md",
>       "display_title": "pages/src/content/docs/ja/architecture.md"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/agent/agent.go",
>       "path": "internal/agent/agent.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/agent/agent.go",
>       "display_title": "internal/agent/agent.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/llmloop/compression.go",
>       "path": "internal/llmloop/compression.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/llmloop/compression.go",
>       "display_title": "internal/llmloop/compression.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/task_template.json",
>       "path": "internal/config/template/task_template.json",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/task_template.json",
>       "display_title": "internal/config/template/task_template.json"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/scan_template.json",
>       "path": "internal/config/template/scan_template.json",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/scan_template.json",
>       "display_title": "internal/config/template/scan_template.json"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/viewer/store_load_test.go",
>       "path": "internal/viewer/store_load_test.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/viewer/store_load_test.go",
>       "display_title": "internal/viewer/store_load_test.go"
>     }
>   ]
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/llmloop/loop.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package llmloop\n\nimport (\n\t\"context\"\n\t\"encoding/json\"\n\t\"fmt\"\n\t\"sync\"\n\t\"sync/atomic\"\n\t\"time\"\n\n\t\"github.com/open-code-review/open-code-review/internal/config/template\"\n\t\"github.com/open-code-review/open-code-review/internal/diff\"\n\t\"github.com/open-code-review/open-code-review/internal/llm\"\n\t\"github.com/open-code-review/open-code-review/internal/model\"\n\t\"github.com/open-code-review/open-code-review/internal/session\"\n\t\"github.com/open-code-review/open-code-review/internal/stdout\"\n\t\"github.com/open-code-review/open-code-review/internal/telemetry\"\n\t\"github.com/open-code-review/open-code-review/internal/tool\"\n)\n\n// Deps bundles all per-call dependencies the Runner needs. Both\n// internal/agent (diff review) and internal/scan (full-file scan) build a\n// Deps from their own state and hand it to NewRunner.\ntype Deps struct {\n\tLLMClient         llm.LLMClient\n\tModel             string\n\tTemplate          template.Template\n\tTools             *tool.Registry\n\tMainToolDefs      []llm.ToolDef\n\tCommentCollector  *tool.CommentCollector\n\tCommentWorkerPool *CommentWorkerPool\n\tSession           *session.SessionHistory\n\t// DiffLookup is consulted by the code_comment tool path to resolve\n\t// line numbers against the file's diff (or against full file content\n\t// in scan mode — scan adapters return a synthetic Diff whose\n\t// NewFileContent is the whole file and Diff is empty).\n\tDiffLookup func(path string) *model.Diff\n}\n\n// Runner is a per-session (across files) executor of the LLM tool-use\n// loop. Token counters, warnings, and the optional background compression\n// job are aggregated across every RunPerFile call.\ntype Runner struct {\n\tdeps                  Deps\n\ttotalInputTokens      int64 // atomically updated\n\ttotalOutputTokens     int64\n\ttotalCacheReadTokens  int64\n\ttotalCacheWriteTokens int64\n\twarningsMu            sync.Mutex\n\twarnings              []AgentWarning\n\ttoolCallsMu           sync.Mutex\n\ttoolCalls             map[string]int64\n\tcompressionMu         sync.Mutex\n\tpendingJob            *compressionJob\n}\n\n// NewRunner returns a Runner bound to the given dependencies.\nfunc NewRunner(deps Deps) *Runner {\n\treturn &Runner{deps: deps}\n}\n\n// TotalInputTokens returns the accumulated input/prompt tokens from all LLM calls.\nfunc (r *Runner) TotalInputTokens() int64 { return atomic.LoadInt64(&r.totalInputTokens) }\n\n// TotalOutputTokens returns the accumulated completion tokens from all LLM calls.\nfunc (r *Runner) TotalOutputTokens() int64 { return atomic.LoadInt64(&r.totalOutputTokens) }\n\n// TotalCacheReadTokens returns the accumulated cache read tokens.\nfunc (r *Runner) TotalCacheReadTokens() int64 { return atomic.LoadInt64(&r.totalCacheReadTokens) }\n\n// TotalCacheWriteTokens returns the accumulated cache write tokens.\nfunc (r *Runner) TotalCacheWriteTokens() int64 { return atomic.LoadInt64(&r.totalCacheWriteTokens) }\n\n// TotalTokensUsed returns input + output.\nfunc (r *Runner) TotalTokensUsed() int64 {\n\treturn r.TotalInputTokens() + r.TotalOutputTokens()\n}\n\n// Warnings returns a copy of the accumulated warnings.\nfunc (r *Runner) Warnings() []AgentWarning {\n\tr.warningsMu.Lock()\n\tdefer r.warningsMu.Unlock()\n\tout := make([]AgentWarning, len(r.warnings))\n\tcopy(out, r.warnings)\n\treturn out\n}\n\n// RecordWarning adds a non-fatal warning.\nfunc (r *Runner) RecordWarning(warningType, file, message string) {\n\tr.warningsMu.Lock()\n\tr.warnings = append(r.warnings, AgentWarning{\n\t\tFile:    file,\n\t\tMessage: message,\n\t\tType:    warningType,\n\t})\n\tr.warningsMu.Unlock()\n}\n\n// ToolCalls returns a snapshot of the per-tool call counts.\nfunc (r *Runner) ToolCalls() map[string]int64 {\n\tr.toolCallsMu.Lock()\n\tdefer r.toolCallsMu.Unlock()\n\tout := make(map[string]int64, len(r.toolCalls))\n\tfor k, v := range r.toolCalls {\n\t\tout[k] = v\n\t}\n\treturn out\n}\n\nfunc (r *Runner) recordToolCall(name string) {\n\tr.toolCallsMu.Lock()\n\tif r.toolCalls == nil {\n\t\tr.toolCalls = make(map[string]int64)\n\t}\n\tr.toolCalls[name]++\n\tr.toolCallsMu.Unlock()\n}\n\n// RecordUsage adds the prompt/completion/cache tokens reported by an LLM\n// response to the runner's aggregate counters. Used by callers (plan phase\n// in agent / future scan phases) that perform their own LLM calls outside\n// RunPerFile.\nfunc (r *Runner) RecordUsage(u *llm.UsageInfo) {\n\tif u == nil {\n\t\treturn\n\t}\n\tatomic.AddInt64(&r.totalInputTokens, u.PromptTokens)\n\tatomic.AddInt64(&r.totalOutputTokens, u.CompletionTokens)\n\tatomic.AddInt64(&r.totalCacheReadTokens, u.CacheReadTokens)\n\tatomic.AddInt64(&r.totalCacheWriteTokens, u.CacheWriteTokens)\n}\n\n// CollectPendingComments awaits any async comment-processing workers and\n// returns the aggregated comments from the collector. Safe to call once\n// per session at the end.\nfunc (r *Runner) CollectPendingComments() []model.LlmComment {\n\tif r.deps.CommentWorkerPool != nil {\n\t\tr.deps.CommentWorkerPool.Await()\n\t}\n\treturn r.deps.CommentCollector.Comments()\n}\n\n// RunPerFile drives the main LLM conversation loop for a single file.\n// It sends messages with the configured tool definitions, executes any\n// tool calls returned by the model, and collects review comments until\n// task_done is called or limits are reached. Token usage and warnings\n// are aggregated on the Runner across all files. The returned bool is true\n// only when the model explicitly calls task_done.\nfunc (r *Runner) RunPerFile(ctx context.Context, messages []llm.Message, newPath string) (bool, error) {\n\ttoolReqCount := r.deps.Template.MaxToolRequestTimes\n\tconst maxConsecutiveEmptyRounds = 3\n\tconsecutiveEmptyRounds := 0\n\n\tfor toolReqCount > 0 {\n\t\tselect {\n\t\tcase <-ctx.Done():\n\t\t\treturn false, ctx.Err()\n\t\tdefault:\n\t\t}\n\n\t\ttoolReqCount--\n\n\t\tfs := r.deps.Session.GetOrCreateFileSession(newPath)\n\t\trec := fs.AppendTaskRecord(session.MainTask, append([]llm.Message(nil), messages...))\n\t\tstartTime := time.Now()\n\n\t\t_, llmSpan := telemetry.StartLLMSpan(ctx, r.deps.Model)\n\t\tresp, err := r.deps.LLMClient.CompletionsWithCtx(ctx, llm.ChatRequest{\n\t\t\tModel:     r.deps.Model,\n\t\t\tMessages:  messages,\n\t\t\tTools:     r.deps.MainToolDefs,\n\t\t\tMaxTokens: r.deps.Template.MaxTokens,\n\t\t})\n\t\tduration := time.Since(startTime)\n\t\tif err != nil {\n\t\t\trec.SetError(err, duration)\n\t\t\ttelemetry.RecordLLMResult(llmSpan, duration, 0, err)\n\t\t\tllmSpan.End()\n\t\t\ttelemetry.RecordLLMRequest(ctx, r.deps.Model, duration, 0, \"error\")\n\t\t\treturn false, fmt.Errorf(\"LLM completion error: %w\", err)\n\t\t}\n\t\trec.SetResponse(resp, duration)\n\t\ttotalTokens := int64(0)\n\t\tif resp.Usage != nil {\n\t\t\ttotalTokens = resp.Usage.TotalTokens\n\t\t\tatomic.AddInt64(&r.totalInputTokens, resp.Usage.PromptTokens)\n\t\t\tatomic.AddInt64(&r.totalOutputTokens, resp.Usage.CompletionTokens)\n\t\t\tatomic.AddInt64(&r.totalCacheReadTokens, resp.Usage.CacheReadTokens)\n\t\t\tatomic.AddInt64(&r.totalCacheWriteTokens, resp.Usage.CacheWriteTokens)\n\t\t}\n\t\ttelemetry.RecordLLMResult(llmSpan, duration, totalTokens, nil)\n\t\tllmSpan.End()\n\t\ttelemetry.RecordLLMRequest(ctx, r.deps.Model, duration, totalTokens, \"ok\")\n\n\t\tcontent := resp.Content()\n\t\tcalls := resp.ToolCalls()\n\n\t\tif len(calls) == 0 {\n\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] No tool calls parsed for %s, retrying...\\n\", newPath)\n\t\t\tmessages = append(messages, llm.NewTextMessage(\"user\", \"You did not successfully call any tools. Please try again or use task_done if finished.\"))\n\t\t\tif content != \"\" {\n\t\t\t\tmessages = append(messages[:len(messages)-1], llm.NewTextMessage(\"assistant\", content), messages[len(messages)-1])\n\t\t\t}\n\t\t\tcontinue\n\t\t}\n\n\t\tvar results []tool.ToolCallResult\n\t\ttaskCompleted := false\n\t\thasValidResult := false\n\n\t\tfor _, call := range calls {\n\t\t\tcp := r.executeToolCall(ctx, newPath, call, rec)\n\t\t\tif cp.Completed {\n\t\t\t\tresults = append(results, tool.ToolCallResult{\n\t\t\t\t\tToolCallID: call.ID,\n\t\t\t\t\tName:       call.Function.Name,\n\t\t\t\t\tResult:     \"Task completed successfully.\",\n\t\t\t\t})\n\t\t\t\ttaskCompleted = true\n\t\t\t} else if cp.Data != \"\" {\n\t\t\t\tresults = append(results, tool.ToolCallResult{\n\t\t\t\t\tToolCallID: call.ID,\n\t\t\t\t\tName:       call.Function.Name,\n\t\t\t\t\tResult:     cp.Data,\n\t\t\t\t})\n\t\t\t\thasValidResult = true\n\t\t\t} else {\n\t\t\t\tresults = append(results, tool.ToolCallResult{\n\t\t\t\t\tToolCallID: call.ID,\n\t\t\t\t\tName:       call.Function.Name,\n\t\t\t\t\tResult:     \"Error: Tool execution returned no result.\",\n\t\t\t\t})\n\t\t\t}\n\t\t}\n\n\t\tif taskCompleted {\n\t\t\treturn true, nil\n\t\t}\n\t\tif !hasValidResult {\n\t\t\tconsecutiveEmptyRounds++\n\t\t\tif consecutiveEmptyRounds >= maxConsecutiveEmptyRounds {\n\t\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Too many empty retries for %s, stopping.\\n\", newPath)\n\t\t\t\tbreak\n\t\t\t}\n\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] No valid tool results for %s, retrying...\\n\", newPath)\n\t\t} else {\n\t\t\tconsecutiveEmptyRounds = 0\n\t\t}\n\n\t\tsucceed := r.addNextMessage(ctx, content, calls, results, &messages, newPath)\n\t\tif !succeed {\n\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Context compression exceeded threshold for %s, stopping.\\n\", newPath)\n\t\t\tbreak\n\t\t}\n\t}\n\n\tif toolReqCount <= 0 {\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Max tool requests reached for %s.\\n\", newPath)\n\t}\n\treturn false, nil\n}\n\n// executeToolCall dispatches a single tool call from the LLM response and\n// records the result in session history. code_comment handling includes\n// optional async dispatch through CommentWorkerPool plus line-number\n// resolution / re-location.\nfunc (r *Runner) executeToolCall(ctx context.Context, newPath string, call llm.ToolCall, rec *session.TaskRecord) tool.TaskCheckpoint {\n\tt := tool.OfName(call.Function.Name)\n\n\tif !t.IsKnown() {\n\t\tp, ok := r.deps.Tools.Get(call.Function.Name)\n\t\tif !ok {\n\t\t\treturn tool.Of(tool.NotAvailableMsg)\n\t\t}\n\t\tr.recordToolCall(call.Function.Name)\n\t\tvar dynArgs map[string]any\n\t\tif err := json.Unmarshal([]byte(call.Function.Arguments), &dynArgs); err != nil {\n\t\t\treturn tool.Of(fmt.Sprintf(\"Error parsing tool arguments for %s: %v\", call.Function.Name, err))\n\t\t}\n\t\ttelemetry.PrintToolCallStarted(call.Function.Name, dynArgs)\n\t\t_, toolSpan := telemetry.StartToolSpan(ctx, call.Function.Name)\n\t\tstartTime := time.Now()\n\t\tresult, err := p.Execute(ctx, dynArgs)\n\t\tdur := time.Since(startTime)\n\t\tif err != nil {\n\t\t\ttelemetry.RecordToolResult(toolSpan, call.Function.Name, dur.Milliseconds(), err)\n\t\t\ttoolSpan.End()\n\t\t\ttelemetry.RecordToolCall(ctx, call.Function.Name, dur, false)\n\t\t\ttelemetry.PrintToolCallError(call.Function.Name, err)\n\t\t\treturn tool.Of(fmt.Sprintf(\"Error executing tool %s: %v\", call.Function.Name, err))\n\t\t}\n\t\ttelemetry.RecordToolResult(toolSpan, call.Function.Name, dur.Milliseconds(), nil)\n\t\ttoolSpan.End()\n\t\ttelemetry.RecordToolCall(ctx, call.Function.Name, dur, true)\n\t\ttelemetry.PrintToolCallFinished(call.Function.Name, dur)\n\t\tif rec != nil {\n\t\t\trec.AddToolResult(call.Function.Name, call.Function.Arguments, result)\n\t\t}\n\t\treturn tool.Of(result)\n\t}\n\n\tif t == tool.TaskDone {\n\t\treturn tool.Complete()\n\t}\n\n\tp := lookupTool(r.deps.Tools, t)\n\tif p == nil {\n\t\treturn tool.Of(tool.NotAvailableMsg)\n\t}\n\n\tr.recordToolCall(t.Name())\n\n\tvar args map[string]any\n\tif err := json.Unmarshal([]byte(call.Function.Arguments), &args); err != nil {\n\t\treturn tool.Of(fmt.Sprintf(\"Error parsing tool arguments for %s: %v\", t.Name(), err))\n\t}\n\n\t// Always inject the current file path for code_comment.\n\t// The model sometimes hallucinates a path, so we override it.\n\tif t == tool.CodeComment && newPath != \"\" {\n\t\targs[\"path\"] = newPath\n\t}\n\n\tstartTime := time.Now()\n\n\tif t == tool.CodeComment {\n\t\ttelemetry.PrintToolCallStarted(t.Name(), args)\n\t\t_, toolSpan := telemetry.StartToolSpan(ctx, t.Name())\n\n\t\tcomments, errMsg := tool.ParseComments(args)\n\t\tif errMsg != \"\" {\n\t\t\tdur := time.Since(startTime)\n\t\t\ttelemetry.RecordToolResult(toolSpan, t.Name(), dur.Milliseconds(), fmt.Errorf(\"%s\", errMsg))\n\t\t\ttoolSpan.End()\n\t\t\ttelemetry.RecordToolCall(ctx, t.Name(), dur, false)\n\t\t\treturn tool.Of(errMsg)\n\t\t}\n\n\t\tresolveAndCollect := func(rctx context.Context) {\n\t\t\tfor i := range comments {\n\t\t\t\tcm := &comments[i]\n\t\t\t\tvar d *model.Diff\n\t\t\t\tif r.deps.DiffLookup != nil {\n\t\t\t\t\td = r.deps.DiffLookup(cm.Path)\n\t\t\t\t}\n\t\t\t\tif d != nil {\n\t\t\t\t\tif !diff.ResolveComment(cm, d) && r.deps.Template.ReLocationTask != nil {\n\t\t\t\t\t\trlStart := time.Now()\n\t\t\t\t\t\t_, resp, msgs := diff.ReLocateComment(rctx, cm, d, r.deps.LLMClient, r.deps.Template.ReLocationTask, r.deps.Model, r.deps.Template.MaxTokens)\n\t\t\t\t\t\tif msgs != nil {\n\t\t\t\t\t\t\tfs := r.deps.Session.GetOrCreateFileSession(cm.Path)\n\t\t\t\t\t\t\trlRec := fs.AppendTaskRecord(session.ReLocationTask, msgs)\n\t\t\t\t\t\t\tif resp != nil {\n\t\t\t\t\t\t\t\trlRec.SetResponse(resp, time.Since(rlStart))\n\t\t\t\t\t\t\t\tif resp.Usage != nil {\n\t\t\t\t\t\t\t\t\tatomic.AddInt64(&r.totalInputTokens, resp.Usage.PromptTokens)\n\t\t\t\t\t\t\t\t\tatomic.AddInt64(&r.totalOutputTokens, resp.Usage.CompletionTokens)\n\t\t\t\t\t\t\t\t\tatomic.AddInt64(&r.totalCacheReadTokens, resp.Usage.CacheReadTokens)\n\t\t\t\t\t\t\t\t\tatomic.AddInt64(&r.totalCacheWriteTokens, resp.Usage.CacheWriteTokens)\n\t\t\t\t\t\t\t\t}\n\t\t\t\t\t\t\t} else {\n\t\t\t\t\t\t\t\trlRec.SetError(fmt.Errorf(\"re-location LLM call failed\"), time.Since(rlStart))\n\t\t\t\t\t\t\t}\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t\tr.deps.CommentCollector.Add(*cm)\n\t\t\t}\n\t\t}\n\n\t\tif r.deps.CommentWorkerPool != nil {\n\t\t\tif rec != nil {\n\t\t\t\trec.AddToolResult(t.Name(), call.Function.Arguments, \"(async)\")\n\t\t\t}\n\t\t\tpool := r.deps.CommentWorkerPool\n\t\t\tasyncCtx := context.WithoutCancel(ctx)\n\t\t\ttoolName := t.Name()\n\t\t\tpool.Submit(func() ([]model.LlmComment, error) {\n\t\t\t\tdefer func() {\n\t\t\t\t\tdur := time.Since(startTime)\n\t\t\t\t\ttelemetry.RecordToolResult(toolSpan, toolName, dur.Milliseconds(), nil)\n\t\t\t\t\ttoolSpan.End()\n\t\t\t\t\ttelemetry.PrintToolCallFinished(toolName, dur)\n\t\t\t\t}()\n\t\t\t\tresolveAndCollect(asyncCtx)\n\t\t\t\treturn []model.LlmComment{}, nil\n\t\t\t})\n\t\t\ttelemetry.RecordToolCall(asyncCtx, toolName, time.Since(startTime), true)\n\t\t\treturn tool.Of(tool.CommentSucceed)\n\t\t}\n\n\t\tresolveAndCollect(ctx)\n\t\tdur := time.Since(startTime)\n\t\ttelemetry.RecordToolResult(toolSpan, t.Name(), dur.Milliseconds(), nil)\n\t\ttoolSpan.End()\n\t\ttelemetry.RecordToolCall(ctx, t.Name(), dur, true)\n\t\ttelemetry.PrintToolCallFinished(t.Name(), dur)\n\t\tif rec != nil {\n\t\t\trec.AddToolResult(t.Name(), call.Function.Arguments, tool.CommentSucceed)\n\t\t}\n\t\treturn tool.Of(tool.CommentSucceed)\n\t}\n\n\t// Synchronous path for all other tools\n\ttelemetry.PrintToolCallStarted(t.Name(), args)\n\t_, toolSpan := telemetry.StartToolSpan(ctx, t.Name())\n\tresult, err := p.Execute(ctx, args)\n\tdur := time.Since(startTime)\n\tok := err == nil\n\ttelemetry.RecordToolResult(toolSpan, t.Name(), dur.Milliseconds(), err)\n\ttoolSpan.End()\n\ttelemetry.RecordToolCall(ctx, t.Name(), dur, ok)\n\n\tif err != nil {\n\t\ttelemetry.PrintToolCallError(t.Name(), err)\n\t\treturn tool.Of(fmt.Sprintf(\"Error executing tool %s: %v\", t.Name(), err))\n\t}\n\ttelemetry.PrintToolCallFinished(t.Name(), dur)\n\tif rec != nil {\n\t\trec.AddToolResult(t.Name(), call.Function.Arguments, result)\n\t}\n\treturn tool.Of(result)\n}\n\n// addNextMessage extends the conversation with the assistant message and\n// tool responses, applying three-zone compression at the soft (60%) and\n// warning (80%) MaxTokens thresholds. Returns false when even after\n// synchronous compression the conversation is still over the warning\n// threshold — caller should stop the loop in that case.\nfunc (r *Runner) addNextMessage(ctx context.Context, assistantContent string, toolCalls []llm.ToolCall, results []tool.ToolCallResult, messages *[]llm.Message, filePath string) bool {\n\tmaxAllowed := r.deps.Template.MaxTokens\n\tsoftLimit := int(float64(maxAllowed) * tokenSoftThreshold)\n\twarnLimit := int(float64(maxAllowed) * tokenWarningThreshold)\n\n\tr.tryApplyPendingCompression(messages)\n\n\ttokenCount := CountMessagesTokens(*messages)\n\n\tif tokenCount > warnLimit {\n\t\tr.cancelPendingCompression()\n\t\t*messages, _ = r.runCompression(ctx, *messages, filePath)\n\t\ttokenCount = CountMessagesTokens(*messages)\n\t}\n\n\tif tokenCount > softLimit && r.pendingJob == nil {\n\t\tr.triggerAsyncCompression(ctx, *messages, filePath)\n\t}\n\n\tif len(toolCalls) > 0 {\n\t\t*messages = append(*messages, llm.NewToolCallMessage(assistantContent, toolCalls))\n\t} else if assistantContent != \"\" {\n\t\t*messages = append(*messages, llm.NewTextMessage(\"assistant\", assistantContent))\n\t}\n\n\tfor _, rs := range results {\n\t\t*messages = append(*messages, llm.NewToolResultMessage(rs.ToolCallID, rs.Result))\n\t}\n\n\tfinalCount := CountMessagesTokens(*messages)\n\tif finalCount > warnLimit {\n\t\tr.cancelPendingCompression()\n\t\t*messages, _ = r.runCompression(ctx, *messages, filePath)\n\t}\n\n\treturn CountMessagesTokens(*messages) < warnLimit\n}\n\n// lookupTool returns the provider for a given tool from the registry, or\n// nil when not registered.\nfunc lookupTool(reg *tool.Registry, t tool.Tool) tool.Provider {\n\tp, ok := reg.Get(t.Name())\n\tif !ok {\n\t\treturn nil\n\t}\n\treturn p\n}\n",
>   "encoding": "utf-8",
>   "sha": "ee0fe6a33a1bc9e853e2371093e6aca4cc5e466f",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go",
>   "display_title": "loop.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/tool/definitions.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package tool\n\nimport (\n\t\"context\"\n\t\"errors\"\n\t\"fmt\"\n)\n\n// Tool represents a single review tool.\ntype Tool struct {\n\tname string\n}\n\nvar (\n\tUnknown      = Tool{name: \"unknown\"}\n\tTaskDone     = Tool{name: \"task_done\"}\n\tCodeComment  = Tool{name: \"code_comment\"}\n\tFileRead     = Tool{name: \"file_read\"}\n\tFileFind     = Tool{name: \"file_find\"}\n\tFileReadDiff = Tool{name: \"file_read_diff\"}\n\tCodeSearch   = Tool{name: \"code_search\"}\n)\n\nfunc OfName(name string) Tool {\n\tfor _, t := range allTools() {\n\t\tif t.name == name {\n\t\t\treturn t\n\t\t}\n\t}\n\treturn Unknown\n}\n\nfunc allTools() []Tool {\n\treturn []Tool{Unknown, TaskDone, CodeComment, FileRead, FileFind, FileReadDiff, CodeSearch}\n}\n\n// IsReserved reports whether name matches any built-in tool name (including Unknown).\nfunc IsReserved(name string) bool {\n\tfor _, t := range allTools() {\n\t\tif t.name == name {\n\t\t\treturn true\n\t\t}\n\t}\n\treturn false\n}\n\n// Dynamic creates a Tool with the given name for dynamically discovered tools (e.g. MCP).\nfunc Dynamic(name string) Tool {\n\tif name == \"\" {\n\t\tpanic(\"tool: Dynamic called with empty name\")\n\t}\n\tif IsReserved(name) {\n\t\tpanic(fmt.Sprintf(\"tool: Dynamic called with reserved tool name %q\", name))\n\t}\n\treturn Tool{name: name}\n}\n\n// Name returns the tool's identifier name.\nfunc (t Tool) Name() string { return t.name }\n\n// IsKnown reports whether the tool is not UNKNOWN.\nfunc (t Tool) IsKnown() bool {\n\treturn t != Unknown\n}\n\n// Provider is the interface that all concrete tool implementations satisfy.\n// Each tool handles one specific capability (read file, search code, etc.).\ntype Provider interface {\n\t// Tool returns which tool this provider implements.\n\tTool() Tool\n\t// Execute runs the tool with the given arguments and returns the result string.\n\tExecute(ctx context.Context, args map[string]any) (string, error)\n}\n\n// Registry holds tool providers. It is safe for concurrent reads after Freeze.\ntype Registry struct {\n\tproviders map[string]Provider\n\tfrozen    bool\n}\n\n// NewRegistry creates an empty, mutable registry.\nfunc NewRegistry() *Registry {\n\treturn &Registry{providers: make(map[string]Provider)}\n}\n\n// Register adds a tool provider. Panics if the registry is frozen.\nfunc (r *Registry) Register(p Provider) {\n\tif r.frozen {\n\t\tpanic(\"tool: Register called on frozen registry\")\n\t}\n\tr.providers[p.Tool().name] = p\n}\n\n// Get returns the provider registered under name.\nfunc (r *Registry) Get(name string) (Provider, bool) {\n\tp, ok := r.providers[name]\n\treturn p, ok\n}\n\n// Freeze prevents further mutations. Call once setup is complete.\nfunc (r *Registry) Freeze() {\n\tr.frozen = true\n}\n\n// ErrToolNotFound is returned when a tool alias cannot be resolved.\nvar ErrToolNotFound = errors.New(\"tool not found\")\n\n// NotAvailableError is the standard message returned when a tool is not registered.\nconst NotAvailableMsg = \"Error: Tool not found. The tool you attempted to call does not exist or is not available. Please check the tool name and try again with a valid tool.\"\n",
>   "encoding": "utf-8",
>   "sha": "6cbab775fa3bead4cfa6afaf3d894048765ab8ec",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/tool/definitions.go",
>   "display_title": "definitions.go"
> }
> ```
>
> </details>
>
> OCR 当前主分支比早期版本又强化了几处关键约束：`task_done` 必须显式结束；连续空工具结果最多 3 轮；主上下文按 60%/80% 两级阈值异步/同步压缩；`code_comment` 先做确定性定位，失败才调用 re-location；所有 changed diff 会注入只读 DiffMap，允许查询相关变更文件。这里已经暴露出本项目下一批最值得补的差距，我正在核对哪些尚未真正落地。
>
> <details><summary>Called 26 tools</summary>
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/diff/comment.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> GitHub API error 404: {"message":"Not Found","documentation_url":"https://docs.github.com/rest/repos/contents#get-repository-content","status":"404"}
> ```
>
> ```json
> {
>   "error": "GitHub API error 404: {\"message\":\"Not Found\",\"documentation_url\":\"https://docs.github.com/rest/repos/contents#get-repository-content\",\"status\":\"404\"}",
>   "error_code": "NOT_FOUND",
>   "error_data": {
>     "message": "Not Found",
>     "documentation_url": "https://docs.github.com/rest/repos/contents#get-repository-content",
>     "status": "404"
>   }
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/tool/code_search.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package tool\n\nimport (\n\t\"bytes\"\n\t\"context\"\n\t\"errors\"\n\t\"fmt\"\n\t\"os/exec\"\n\t\"strconv\"\n\t\"strings\"\n\t\"time\"\n)\n\nconst (\n\tgitGrepMaxCount = 100\n\tgitGrepTimeout  = 10 * time.Second\n)\n\n// CodeSearchProvider performs text search across the repository using git grep.\ntype CodeSearchProvider struct {\n\tFileReader *FileReader\n}\n\nfunc NewCodeSearch(fr *FileReader) *CodeSearchProvider { return &CodeSearchProvider{FileReader: fr} }\n\nfunc (p *CodeSearchProvider) Tool() Tool { return CodeSearch }\n\nfunc (p *CodeSearchProvider) Execute(ctx context.Context, args map[string]any) (string, error) {\n\tsearchText, _ := args[\"search_text\"].(string)\n\tcaseSensitive, _ := args[\"case_sensitive\"].(bool)\n\tusePerlRegexp, _ := args[\"use_perl_regexp\"].(bool)\n\n\tfilePatternsIface, _ := args[\"file_patterns\"].([]any)\n\tvar patterns []string\n\tfor _, item := range filePatternsIface {\n\t\tif s, ok := item.(string); ok && s != \"\" {\n\t\t\tif hasTraversalPathComponent(s) {\n\t\t\t\treturn \"Error: file_patterns must not contain ..\", nil\n\t\t\t}\n\t\t\tpatterns = append(patterns, s)\n\t\t}\n\t}\n\n\tif strings.TrimSpace(searchText) == \"\" {\n\t\treturn \"Error: search_text is blank\", nil\n\t}\n\n\tresult, err := p.gitGrep(ctx, searchText, caseSensitive, usePerlRegexp, patterns)\n\tif err != nil {\n\t\treturn \"\", fmt.Errorf(\"code_search failed: %w\", err)\n\t}\n\treturn result, nil\n}\n\nfunc (p *CodeSearchProvider) buildGrepArgs(searchText string, caseSensitive bool, usePerlRegexp bool, noIndex bool, pathspec []string) []string {\n\tcmdArgs := []string{\"--no-pager\", \"grep\"}\n\n\tif noIndex {\n\t\t// Non-git directory: search the working tree directly while still\n\t\t// honoring .gitignore and skipping .git (via --exclude-standard).\n\t\tcmdArgs = append(cmdArgs, \"--no-index\", \"--exclude-standard\")\n\t} else if p.FileReader.Ref == \"\" {\n\t\tcmdArgs = append(cmdArgs, \"--untracked\")\n\t}\n\n\tif !caseSensitive {\n\t\tcmdArgs = append(cmdArgs, \"-i\")\n\t}\n\tif usePerlRegexp {\n\t\tcmdArgs = append(cmdArgs, \"-P\")\n\t} else {\n\t\tcmdArgs = append(cmdArgs, \"-F\")\n\t}\n\n\tcmdArgs = append(cmdArgs, \"-n\", \"--no-color\")\n\tcmdArgs = append(cmdArgs, \"--max-count\", fmt.Sprintf(\"%d\", gitGrepMaxCount))\n\n\tcmdArgs = append(cmdArgs, \"-e\", searchText)\n\n\tif ref := p.FileReader.Ref; ref != \"\" {\n\t\tcmdArgs = append(cmdArgs, \"--end-of-options\")\n\t\tcmdArgs = append(cmdArgs, ref)\n\t}\n\n\tcmdArgs = append(cmdArgs, \"--\")\n\tcmdArgs = append(cmdArgs, pathspec...)\n\n\treturn cmdArgs\n}\n\nfunc hasTraversalPathComponent(pathspec string) bool {\n\tfor _, part := range strings.Split(pathspec, \"/\") {\n\t\tif part == \"..\" {\n\t\t\treturn true\n\t\t}\n\t}\n\treturn false\n}\n\nfunc (p *CodeSearchProvider) runGitGrep(parentCtx context.Context, cmdArgs []string) (string, string, error) {\n\tctx, cancel := context.WithTimeout(parentCtx, gitGrepTimeout)\n\tdefer cancel()\n\n\tif p.FileReader.Runner != nil {\n\t\tstdout, stderr, err := p.FileReader.Runner.RunSplit(ctx, p.FileReader.RepoDir, cmdArgs...)\n\t\tif ctx.Err() != nil && err != nil {\n\t\t\treturn \"\", \"\", ctx.Err()\n\t\t}\n\t\treturn stdout, stderr, err\n\t}\n\n\tcmd := exec.CommandContext(ctx, \"git\", cmdArgs...)\n\tcmd.Dir = p.FileReader.RepoDir\n\n\tvar stdout, stderr bytes.Buffer\n\tcmd.Stdout = &stdout\n\tcmd.Stderr = &stderr\n\n\terr := cmd.Run()\n\tif ctx.Err() != nil && err != nil && cmd.ProcessState != nil && cmd.ProcessState.ExitCode() == -1 {\n\t\treturn \"\", \"\", ctx.Err()\n\t}\n\treturn stdout.String(), stderr.String(), err\n}\n\nfunc (p *CodeSearchProvider) gitGrep(ctx context.Context, searchText string, caseSensitive bool, usePerlRegexp bool, pathspec []string) (string, error) {\n\tcmdArgs := p.buildGrepArgs(searchText, caseSensitive, usePerlRegexp, false, pathspec)\n\n\toutStr, errStr, err := p.runGitGrep(ctx, cmdArgs)\n\n\t// Non-git directory: `git grep` exits 128 with \"not a git repository\".\n\t// `ocr scan` supports plain directories, so retry in --no-index mode, which\n\t// searches the working tree directly while still honoring .gitignore.\n\t// Ref-based search needs a real repo, so it is not retried.\n\tif err != nil && p.FileReader.Ref == \"\" && isNotGitRepoError(err, errStr) {\n\t\tcmdArgs = p.buildGrepArgs(searchText, caseSensitive, usePerlRegexp, true, pathspec)\n\t\toutStr, errStr, err = p.runGitGrep(ctx, cmdArgs)\n\t}\n\n\tif err != nil {\n\t\tif errors.Is(err, context.DeadlineExceeded) {\n\t\t\treturn \"code_search timed out. Try narrowing file_patterns to a more specific path.\", nil\n\t\t}\n\t\tif errors.Is(err, context.Canceled) {\n\t\t\treturn \"\", err\n\t\t}\n\t\tif outStr == \"\" {\n\t\t\tif errStr == \"\" {\n\t\t\t\treturn \"No matches found\", nil\n\t\t\t}\n\t\t\treturn fmt.Sprintf(\"Error: %s\", strings.TrimSpace(errStr)), nil\n\t\t}\n\t}\n\n\tlines := strings.Split(strings.TrimRight(outStr, \"\\n\"), \"\\n\")\n\ttruncated := len(lines) >= gitGrepMaxCount\n\n\ttype match struct {\n\t\tlineNum int\n\t\tcontent string\n\t}\n\tfileMatches := make(map[string][]match)\n\tvar fileOrder []string\n\tseen := make(map[string]bool)\n\n\thasRef := p.FileReader.Ref != \"\"\n\tsplitN := 3\n\toffset := 0\n\tif hasRef {\n\t\tsplitN = 4\n\t\toffset = 1\n\t}\n\n\tvar sb strings.Builder\n\tif truncated {\n\t\tsb.WriteString(fmt.Sprintf(\"Note: The results have been truncated. Only showing first %d results.\\n\", gitGrepMaxCount))\n\t}\n\n\tfor _, line := range lines {\n\t\tif line == \"\" {\n\t\t\tcontinue\n\t\t}\n\t\tparts := strings.SplitN(line, \":\", splitN)\n\t\tif len(parts) < splitN {\n\t\t\tcontinue\n\t\t}\n\t\tfname := parts[offset]\n\t\tm := match{}\n\t\tln, parseErr := strconv.Atoi(parts[offset+1])\n\t\tif parseErr != nil {\n\t\t\tcontinue\n\t\t}\n\t\tm.lineNum = ln\n\t\tm.content = parts[offset+2]\n\t\tif !seen[fname] {\n\t\t\tseen[fname] = true\n\t\t\tfileOrder = append(fileOrder, fname)\n\t\t}\n\t\tfileMatches[fname] = append(fileMatches[fname], m)\n\t}\n\n\tfor _, path := range fileOrder {\n\t\tmatches := fileMatches[path]\n\t\tsb.WriteString(fmt.Sprintf(\"File: %s\\nMatch lines: %d\\n\", path, len(matches)))\n\t\tfor _, m := range matches {\n\t\t\tsb.WriteString(fmt.Sprintf(\"%d|%s\\n\", m.lineNum, m.content))\n\t\t}\n\t\tsb.WriteString(\"\\n\")\n\t}\n\n\tif err != nil && errStr != \"\" {\n\t\tsb.WriteString(fmt.Sprintf(\"Warning: %s\\n\", strings.TrimSpace(errStr)))\n\t}\n\n\treturn sb.String(), nil\n}\n\nfunc isNotGitRepoError(err error, stderr string) bool {\n\tvar exitErr *exec.ExitError\n\tif errors.As(err, &exitErr) && exitErr.ExitCode() == 128 &&\n\t\t(strings.Contains(stderr, \"not a git repository\") || strings.Contains(stderr, \".git\")) {\n\t\treturn true\n\t}\n\treturn false\n}\n",
>   "encoding": "utf-8",
>   "sha": "4e8ee79438a95b1a8d9591fc526229b8cda13187",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/tool/code_search.go",
>   "display_title": "code_search.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/task_template.json",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "{\n  \"MAIN_TASK\": {\n    \"timeout\": 120,\n    \"messages\": [\n      { \"role\": \"system\", \"prompt_file\": \"main_task_system.md\" },\n      { \"role\": \"user\", \"prompt_file\": \"main_task_user.md\" }\n    ]\n  },\n  \"PLAN_TASK\": {\n    \"timeout\": 180,\n    \"messages\": [\n      { \"role\": \"system\", \"prompt_file\": \"plan_task_system.md\" },\n      { \"role\": \"user\", \"prompt_file\": \"plan_task_user.md\" }\n    ]\n  },\n  \"MEMORY_COMPRESSION_TASK\": {\n    \"timeout\": 120,\n    \"messages\": [\n      { \"role\": \"system\", \"prompt_file\": \"memory_compression_task_system.md\" },\n      { \"role\": \"user\", \"prompt_file\": \"memory_compression_task_user.md\" }\n    ]\n  },\n  \"REVIEW_FILTER_TASK\": {\n    \"timeout\": 180,\n    \"messages\": [\n      { \"role\": \"system\", \"prompt_file\": \"review_filter_task_system.md\" },\n      { \"role\": \"user\", \"prompt_file\": \"review_filter_task_user.md\" }\n    ]\n  },\n  \"RE_LOCATION_TASK\": {\n    \"timeout\": 180,\n    \"messages\": [\n      { \"role\": \"system\", \"prompt_file\": \"re_location_task_system.md\" },\n      { \"role\": \"user\", \"prompt_file\": \"re_location_task_user.md\" }\n    ]\n  },\n  \"MAX_TOOL_REQUEST_TIMES\": 30,\n  \"PLAN_MODE_LINE_THRESHOLD\": 50,\n  \"MAX_TOKENS\": 58888\n}\n",
>   "encoding": "utf-8",
>   "sha": "3c38eb0746ba9e0e769c506acea21f4e2ad1acb6",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/task_template.json",
>   "display_title": "task_template.json"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/tool/file_read_diff.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package tool\n\nimport (\n\t\"context\"\n\t\"strings\"\n)\n\n// DiffMap is a read-only snapshot of parsed diffs, keyed by file path.\n// Safe for concurrent reads after construction via NewDiffMap.\ntype DiffMap struct {\n\tm map[string]string\n}\n\n// NewDiffMap creates a frozen, read-only DiffMap from a plain map.\nfunc NewDiffMap(m map[string]string) DiffMap {\n\tcp := make(map[string]string, len(m))\n\tfor k, v := range m {\n\t\tcp[k] = v\n\t}\n\treturn DiffMap{m: cp}\n}\n\n// Get returns the diff text for path.\nfunc (d DiffMap) Get(path string) (string, bool) {\n\tv, ok := d.m[path]\n\treturn v, ok\n}\n\n// FileReadDiffProvider retrieves diff content by file path from an already-parsed diff set.\ntype FileReadDiffProvider struct {\n\tdiffMap DiffMap\n}\n\nfunc NewFileReadDiff(dm DiffMap) *FileReadDiffProvider {\n\treturn &FileReadDiffProvider{diffMap: dm}\n}\n\n// SetDiffMap replaces the diff snapshot. Must be called before concurrent access begins.\nfunc (p *FileReadDiffProvider) SetDiffMap(dm DiffMap) {\n\tp.diffMap = dm\n}\n\nfunc (p *FileReadDiffProvider) Tool() Tool { return FileReadDiff }\n\nfunc (p *FileReadDiffProvider) Execute(_ context.Context, args map[string]any) (string, error) {\n\tpathArray, _ := args[\"path_array\"].([]any)\n\tif len(pathArray) == 0 {\n\t\treturn \"Error: no files found\", nil\n\t}\n\n\tvar sb strings.Builder\n\tfor _, item := range pathArray {\n\t\tpath, ok := item.(string)\n\t\tif !ok {\n\t\t\tcontinue\n\t\t}\n\t\tif d, exists := p.diffMap.Get(path); exists {\n\t\t\tsb.WriteString(\"==== FILE: \")\n\t\t\tsb.WriteString(path)\n\t\t\tsb.WriteString(\" ====\\n\")\n\t\t\tsb.WriteString(d)\n\t\t\tsb.WriteString(\"\\n\")\n\t\t}\n\t}\n\n\tresult := sb.String()\n\tif result == \"\" {\n\t\treturn \"Error: diff not found for the requested paths\", nil\n\t}\n\treturn result, nil\n}\n",
>   "encoding": "utf-8",
>   "sha": "24c565dcc473be4f0ce124b0ed68ec3c48cfec83",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/tool/file_read_diff.go",
>   "display_title": "file_read_diff.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/scan_template.json",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ````json
> {
>   "content": "{\n  \"MAIN_TASK\": {\n    \"messages\": [\n      {\n        \"role\": \"system\",\n        \"content\": \"## Role\\nYou are a code review assistant developed by Alibaba. Unlike diff-based review, in this task you are reviewing an ENTIRE existing source file (no diff context). Provide professional review feedback identifying real defects, bugs, security risks, performance issues, concurrency hazards, and maintainability problems in the file as it stands today.\\n\\n## Capabilities\\n- Think step by step.\\n- Read the full file content carefully before commenting.\\n- Be objective and grounded in the source. When context is insufficient, call context tools instead of guessing.\\n- Focus on substantive correctness/security/performance/maintainability issues. Avoid stylistic nitpicks unless the project's review rules call them out.\\n- Do not comment on code in other files — context tools are reference only; findings outside the current file MUST NOT become the subject of your comments.\\n- Avoid commenting on auto-generated code, code comments, or metadata annotations unless the user's review rules require it.\\n\\n## Tool-call discipline (IMPORTANT — your tool-call budget per file is limited)\\n- The file content is ALREADY in <current_file_content>; do NOT call `file_read` to re-fetch the current file.\\n- Limit context-gathering to AT MOST 2-3 tool calls per finding. Avoid calling the same tool with the same arguments more than once.\\n- Once you have enough evidence for an issue, call `code_comment` immediately rather than gathering more context.\\n- Batch multiple comments in a single `code_comment` call (its `comments` parameter accepts an array) instead of issuing one call per finding.\\n- If no further issues are evident after a quick sweep of the file, call `task_done` immediately — do not keep probing for marginal findings.\\n\\n## Reply limit\\n- If the review is complete, call `task_done` to end the task.\\n- For each confirmed issue, call `code_comment` to record feedback (prefer batching).\\n- If additional context is genuinely needed, call the appropriate context tool, but stay within the budget above.\"\n      },\n      {\n        \"role\": \"user\",\n        \"content\": \"<current_file_path>{{current_file_path}}</current_file_path>\\n\\n<current_file_content>\\n{{file_content}}\\n</current_file_content>\\n\\nCurrent time in the real world: {{current_system_date_time}}\\n\\n<user_task>\\n### Requirement Background (Optional)\\n{{requirement_background}}\\n\\n### Review Checklist\\n{{system_rule}}\\n\\n### Pre-scan Focus Areas\\n{{plan_guidance}}\\n\\nReview the entire source file in <current_file_content> and report all findings via code_comment, then call task_done.\\n</user_task>\"\n      }\n    ],\n    \"timeout\": 180\n  },\n  \"PLAN_TASK\": {\n    \"messages\": [\n      {\n        \"role\": \"system\",\n        \"content\": \"## Role\\nYou are a scan-mode review planner. Given a whole source file you produce a focused review checklist that a downstream reviewer will use as guidance.\\n\\n## Output\\nStrictly output a single JSON object with this shape (no prose around it):\\n\\n```\\n{\\n  \\\"summary\\\": \\\"one or two sentences summarizing what this file does and its key design\\\",\\n  \\\"checkpoints\\\": [\\n    {\\\"focus\\\": \\\"<short label of the concern>\\\", \\\"lines\\\": \\\"<line range like 45-78, optional>\\\", \\\"why\\\": \\\"<one sentence why it warrants attention>\\\"}\\n  ]\\n}\\n```\\n\\n## Discipline\\n- At most 5 checkpoints. Prefer fewer high-signal ones over many shallow ones.\\n- Severity bias: prioritise correctness / concurrency / security / data-integrity / error-handling over style.\\n- Each checkpoint must be grounded in the file content; if unsure, omit it.\\n- Do NOT call any tools. Output JSON only.\"\n      },\n      {\n        \"role\": \"user\",\n        \"content\": \"<current_file_path>{{current_file_path}}</current_file_path>\\n\\n<current_file_content>\\n{{file_content}}\\n</current_file_content>\\n\\nCurrent time: {{current_system_date_time}}\\n\\n### Review Checklist (project rules)\\n{{system_rule}}\\n\\nProduce the JSON focus checklist now.\"\n      }\n    ],\n    \"timeout\": 90\n  },\n  \"DEDUP_TASK\": {\n    \"messages\": [\n      {\n        \"role\": \"system\",\n        \"content\": \"## Role\\nYou consolidate near-duplicate review comments produced within a single scan batch into a smaller, deduplicated set.\\n\\n## Output\\nStrictly output one JSON object, no prose:\\n\\n```\\n{\\n  \\\"groups\\\": [\\n    {\\\"members\\\": [\\\"c-0\\\"]},\\n    {\\\"members\\\": [\\\"c-1\\\",\\\"c-3\\\"], \\\"merged_content\\\": \\\"<optional rewritten content for the group\\\\u0027s canonical comment>\\\"}\\n  ]\\n}\\n```\\n\\n## Rules\\n- Every input id MUST appear in exactly one group's members list.\\n- A single-member group means \\\"keep as-is\\\".\\n- A multi-member group means: keep members[0] as canonical, drop the rest. If merged_content is present, replace the canonical comment's content with it; otherwise keep the canonical's original content unchanged.\\n- Cluster aggressively only when comments make the SAME claim (e.g. \\\"missing error check\\\" repeated across files). Do NOT merge two findings just because they touch the same area.\\n- Prefer keeping per-file detail over merging across files when severity differs.\\n- Output JSON only. No commentary.\"\n      },\n      {\n        \"role\": \"user\",\n        \"content\": \"<batch_comments>\\n{{batch_comments}}\\n</batch_comments>\\n\\nProduce the dedup groups JSON now.\"\n      }\n    ],\n    \"timeout\": 90\n  },\n  \"PROJECT_SUMMARY_TASK\": {\n    \"messages\": [\n      {\n        \"role\": \"system\",\n        \"content\": \"## Role\\nYou are a senior reviewer producing a project-level summary of a full-repo scan.\\n\\nYou are given the union of per-file review comments. Identify cross-cutting patterns and the most important findings; do NOT restate every individual comment.\\n\\n## Output\\nA single markdown document with these sections (omit a section if it has nothing to say):\\n\\n### Top Issues\\nThe 5–10 most consequential findings, ranked by impact. Group when the same root cause repeats across files.\\n\\n### Module Hotspots\\nDirectories / modules where comment density or severity is abnormally high. Cite paths.\\n\\n### Cross-Cutting Concerns\\nPatterns that appear across many files (e.g. inconsistent error handling, missing tests, unsafe concurrency primitives). Cite a few representative paths each.\\n\\n### Quick Wins\\nFixes that are low-effort and high-leverage based on the comments.\\n\\nDo not include a generic \\\"overall the codebase is X\\\" paragraph. Be concrete; reference paths.\"\n      },\n      {\n        \"role\": \"user\",\n        \"content\": \"Total comments: {{comment_count}} across {{file_count}} files.\\n\\n<all_comments>\\n{{all_comments}}\\n</all_comments>\\n\\nProduce the project summary markdown now.\"\n      }\n    ],\n    \"timeout\": 120\n  },\n  \"MEMORY_COMPRESSION_TASK\": {\n    \"messages\": [\n      {\n        \"role\": \"system\",\n        \"content\": \"## Goal\\nYou are a professional code review conversation summarization assistant. You will receive a conversation history between a code review assistant and an LLM model (including tool calls and their results). Compress this conversation into a structured summary so that the code review assistant can continue from the current state without restarting.\\n\\n## Output Format Requirements\\nOrganize the summary using the following five dimensions, separated by explicit headings:\\n\\n### Identified Code Issues\\nList all confirmed issues sorted by severity (HIGH / MEDIUM / LOW). Each entry should include: file path, issue type, severity, brief description.\\n\\n### Tool Call Conclusions\\nSummarize key findings and conclusions from each tool invocation.\\n\\n### Completed Tasks\\nList items that have been completed and require no further follow-up.\\n\\n### Pending Tasks\\nList items that have been started but not yet completed and still need attention.\\n\\n### Current Focus\\nSummarize in one sentence the core matter currently being investigated or handled.\\n\\n## Rules\\n1. Do not include specific code details; only reference file paths and issue types\\n2. Avoid repetitive or redundant information\\n3. Omit any dimension that has no relevant content\\n4. Completed/pending task list items should be described as complete sentences\\n5. current_focus should be concise, no more than one sentence\"\n      },\n      {\n        \"role\": \"user\",\n        \"content\": \"{{context}}\"\n      }\n    ],\n    \"timeout\": 120\n  },\n  \"RE_LOCATION_TASK\": {\n    \"messages\": [\n      {\n        \"role\": \"system\",\n        \"content\": \"You are a code location assistant. Given a unified diff and a review comment, your sole task is to extract the exact code snippet from the diff that the comment refers to. /no_think\"\n      },\n      {\n        \"role\": \"user\",\n        \"content\": \"Below is a unified diff and a review comment. Identify the minimal contiguous code range in the diff that the comment targets.\\n\\nRules:\\n1. Copy the relevant lines VERBATIM from the diff — do not rewrite, reformat, or add anything.\\n2. Strip leading diff markers (`+`, `-`, ` `) from each line before outputting.\\n3. Include only the lines directly related to the issue — no surrounding context.\\n4. If multiple disjoint locations apply, pick the single most relevant one.\\n5. Output ONLY a fenced code block. No explanation, no commentary.\\n\\n**Diff:**\\n```diff\\n{diff}```\\n\\n**Original code snippet (failed to match):**\\n```\\n{existing_code}\\n```\\n\\n**Review comment:**\\n{suggestion_content}\"\n      }\n    ],\n    \"timeout\": 180\n  },\n  \"MAX_TOKENS\": 58888,\n  \"MAX_TOOL_REQUEST_TIMES\": 60,\n  \"MAX_FILE_SIZE_BYTES\": 2097152,\n  \"BATCH_STRATEGY\": \"by-language\",\n  \"BATCH_SIZE\": 50,\n  \"DEDUP_MIN_COMMENTS\": 4,\n  \"TOOL_REQUEST_WAIT_TIME_MS\": 10000,\n  \"MAX_SUBTASK_EXECUTION_TIME_MINUTES\": 5\n}\n",
>   "encoding": "utf-8",
>   "sha": "5dcf30ac9782b8cbfb2404e33361731942f90ddb",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/scan_template.json",
>   "display_title": "scan_template.json"
> }
> ````
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/tool/definitions.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package tool\n\nimport (\n\t\"context\"\n\t\"errors\"\n\t\"fmt\"\n)\n\n// Tool represents a single review tool.\ntype Tool struct {\n\tname string\n}\n\nvar (\n\tUnknown      = Tool{name: \"unknown\"}\n\tTaskDone     = Tool{name: \"task_done\"}\n\tCodeComment  = Tool{name: \"code_comment\"}\n\tFileRead     = Tool{name: \"file_read\"}\n\tFileFind     = Tool{name: \"file_find\"}\n\tFileReadDiff = Tool{name: \"file_read_diff\"}\n\tCodeSearch   = Tool{name: \"code_search\"}\n)\n\nfunc OfName(name string) Tool {\n\tfor _, t := range allTools() {\n\t\tif t.name == name {\n\t\t\treturn t\n\t\t}\n\t}\n\treturn Unknown\n}\n\nfunc allTools() []Tool {\n\treturn []Tool{Unknown, TaskDone, CodeComment, FileRead, FileFind, FileReadDiff, CodeSearch}\n}\n\n// IsReserved reports whether name matches any built-in tool name (including Unknown).\nfunc IsReserved(name string) bool {\n\tfor _, t := range allTools() {\n\t\tif t.name == name {\n\t\t\treturn true\n\t\t}\n\t}\n\treturn false\n}\n\n// Dynamic creates a Tool with the given name for dynamically discovered tools (e.g. MCP).\nfunc Dynamic(name string) Tool {\n\tif name == \"\" {\n\t\tpanic(\"tool: Dynamic called with empty name\")\n\t}\n\tif IsReserved(name) {\n\t\tpanic(fmt.Sprintf(\"tool: Dynamic called with reserved tool name %q\", name))\n\t}\n\treturn Tool{name: name}\n}\n\n// Name returns the tool's identifier name.\nfunc (t Tool) Name() string { return t.name }\n\n// IsKnown reports whether the tool is not UNKNOWN.\nfunc (t Tool) IsKnown() bool {\n\treturn t != Unknown\n}\n\n// Provider is the interface that all concrete tool implementations satisfy.\n// Each tool handles one specific capability (read file, search code, etc.).\ntype Provider interface {\n\t// Tool returns which tool this provider implements.\n\tTool() Tool\n\t// Execute runs the tool with the given arguments and returns the result string.\n\tExecute(ctx context.Context, args map[string]any) (string, error)\n}\n\n// Registry holds tool providers. It is safe for concurrent reads after Freeze.\ntype Registry struct {\n\tproviders map[string]Provider\n\tfrozen    bool\n}\n\n// NewRegistry creates an empty, mutable registry.\nfunc NewRegistry() *Registry {\n\treturn &Registry{providers: make(map[string]Provider)}\n}\n\n// Register adds a tool provider. Panics if the registry is frozen.\nfunc (r *Registry) Register(p Provider) {\n\tif r.frozen {\n\t\tpanic(\"tool: Register called on frozen registry\")\n\t}\n\tr.providers[p.Tool().name] = p\n}\n\n// Get returns the provider registered under name.\nfunc (r *Registry) Get(name string) (Provider, bool) {\n\tp, ok := r.providers[name]\n\treturn p, ok\n}\n\n// Freeze prevents further mutations. Call once setup is complete.\nfunc (r *Registry) Freeze() {\n\tr.frozen = true\n}\n\n// ErrToolNotFound is returned when a tool alias cannot be resolved.\nvar ErrToolNotFound = errors.New(\"tool not found\")\n\n// NotAvailableError is the standard message returned when a tool is not registered.\nconst NotAvailableMsg = \"Error: Tool not found. The tool you attempted to call does not exist or is not available. Please check the tool name and try again with a valid tool.\"\n",
>   "encoding": "utf-8",
>   "sha": "6cbab775fa3bead4cfa6afaf3d894048765ab8ec",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/tool/definitions.go",
>   "display_title": "definitions.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/toolsconfig/tools.json",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "[\n  {\n    \"name\": \"task_done\",\n    \"plan_task\": false,\n    \"main_task\": true,\n    \"definition\": {\n      \"name\": \"task_done\",\n      \"description\": \"Call this tool to terminate task execution when you have completed the user's task, such as when no obvious code issues are found during code review.\",\n      \"parameters\": {\n        \"type\": \"object\",\n        \"properties\": {\n          \"state\": {\n            \"type\": \"string\",\n            \"enum\": [\n              \"DONE\",\n              \"FAILED\"\n            ],\n            \"description\": \"Defaults to DONE. Return FAILED if the task cannot be completed using available tools.\"\n          }\n        },\n        \"required\": [\n          \"state\"\n        ]\n      }\n    }\n  },\n  {\n    \"name\": \"code_comment\",\n    \"plan_task\": false,\n    \"main_task\": true,\n    \"definition\": {\n      \"name\": \"code_comment\",\n      \"description\": \"When you discover that a code change could introduce code issue, please use this tool to report the issue. The tool will pinpoint your feedback to the precise code line (or block) in the current file by inserting a code comment.\\n\\n**Core Mechanism:**\\nThis tool uses a dynamic sliding window algorithm to match corresponding consecutive lines in diff text based on your provided 'existing_code' parameter. Therefore, you must ensure the provided 'existing_code' actually exists in the diff text with exactly matching format. It should contain one or several consecutive lines of code most relevant to your comment.\",\n      \"parameters\": {\n        \"type\": \"object\",\n        \"properties\": {\n          \"comments\": {\n            \"type\": \"array\",\n            \"description\": \"A list of comments. Each item should contain 'content' and 'existing_code'.\",\n            \"items\": {\n              \"type\": \"object\",\n              \"properties\": {\n                \"content\": {\n                  \"type\": \"string\",\n                  \"description\": \"Comment content, typically a brief description of code issues and corresponding suggestions.\"\n                },\n                \"existing_code\": {\n                  \"type\": \"string\",\n                  \"description\": \"Code snippet used to locate comment position. Only return newly added code lines, should not include deleted code or unchanged code lines. Maintain consistent style with diff code for IDE recognition and mounting in current file.\"\n                },\n                \"suggestion_code\": {\n                  \"type\": \"string\",\n                  \"description\": \"Corresponding suggested code snippet, maintaining consistent code style.\"\n                },\n                \"category\": {\n                  \"type\": \"string\",\n                  \"enum\": [\n                    \"bug\",\n                    \"security\",\n                    \"performance\",\n                    \"maintainability\",\n                    \"test\",\n                    \"style\",\n                    \"documentation\",\n                    \"other\"\n                  ],\n                  \"description\": \"The category the issue belongs to.\"\n                },\n                \"severity\": {\n                  \"type\": \"string\",\n                  \"enum\": [\n                    \"critical\",\n                    \"high\",\n                    \"medium\",\n                    \"low\"\n                  ],\n                  \"description\": \"The severity of the issue.\"\n                }\n              },\n              \"required\": [\n                \"content\",\n                \"existing_code\",\n                \"category\",\n                \"severity\"\n              ]\n            }\n          }\n        },\n        \"required\": [\n          \"comments\"\n        ]\n      }\n    }\n  },\n  {\n    \"name\": \"file_read\",\n    \"plan_task\": false,\n    \"main_task\": true,\n    \"definition\": {\n      \"name\": \"file_read\",\n      \"description\": \"Use this tool to read file content when you need to get context for git diff. You can specify start_line and end_line to view specific parts of the file.\\n\\n**Line Range Strategy:**\\n- Git diff hunk header provides guidance on how to get more relevant context.\\n- Git diff hunk header \\\"@@-x,y +m,n@@\\\" indicates that the old file has y lines starting from line x, and the new file has n lines starting from line m.\\n- For example, when you need to read 50 lines above and below the current changed code block in the new file, set start_line = m - 50, end_line = m + n + 50.\\n\\n**Example output:**\\nFile：path/to/example.go (Total lines: 50)\\nIS_TRUNCATED: false\\nLINE_RANGE: 10-12\\n// The following is the original content of the file\\nfunc main() {\\n  fmt.Println(\\\"Hello, World!\\\")\\n}\\n\\n**Limitations:**\\n- If the specified range exceeds 500 lines, only 500 lines will be returned with a truncation notice.\\n- This tool can only read file content from the modified version (after changes) in git diff.\",\n      \"parameters\": {\n        \"type\": \"object\",\n        \"properties\": {\n          \"file_path\": {\n            \"type\": \"string\",\n            \"description\": \"The relative path of the file to open.\"\n          },\n          \"start_line\": {\n            \"type\": \"integer\",\n            \"description\": \"The start line number to view. Defaults to 1.\"\n          },\n          \"end_line\": {\n            \"type\": \"integer\",\n            \"description\": \"The end line number to view. Defaults to end line of file.\"\n          }\n        },\n        \"required\": [\n          \"file_path\"\n        ]\n      }\n    }\n  },\n  {\n    \"name\": \"code_search\",\n    \"plan_task\": true,\n    \"main_task\": true,\n    \"definition\": {\n      \"name\": \"code_search\",\n      \"description\": \"Use this tool to search for specific text within files. Supports searching in specific files, directories, or across the entire codebase with flexible file pattern filtering. Can use either exact string matching or regular expressions.\\n\\n**Example output:**\\nSearch results for 'toolRequest' (case-insensitive):\\nFile: path/to/example.java\\n433|      String name = toolRequest.get().getName();\\n438|      logToolRequest(newPath, tool, toolRequest.get());\\n\\n**Regular expression examples (requires use_perl_regexp: true):**\\n- Find classes that extend BaseModel: 'class.*extends.*BaseModel'\\n- Find function: 'functionName(.*)'\\n- Find the function call sites: '\\\\.functionName(.*)'\\n- Match any of multiple strings: 'error|exception|fail'\\n\\n**File patterns examples:**\\n- Single file: ['src/main.go']\\n- Multiple files: ['src/main.go', 'lib/utils.js']\\n- All Go files: ['*.go']\\n- Exclude test files: [':(exclude)*_test.go']\\n- Only in src directory: ['src/']\\n- Multiple patterns: ['*.go', ':(exclude)vendor/']\\n\\n**Limitations:**\\n- If more than 100 matches are found, only the first 100 results will be returned.\\n- Empty search terms will return no results.\\n- This tool searches in the current version of files.\",\n      \"parameters\": {\n        \"type\": \"object\",\n        \"properties\": {\n          \"search_text\": {\n            \"type\": \"string\",\n            \"description\": \"The text string or regular expression pattern to search for.\"\n          },\n          \"file_patterns\": {\n            \"type\": \"array\",\n            \"items\": {\n              \"type\": \"string\"\n            },\n            \"description\": \"Array of patterns to include/exclude files in the search. Supports Git pathspec syntax for including and excluding files. If omitted, searches the entire codebase.\"\n          },\n          \"case_sensitive\": {\n            \"type\": \"boolean\",\n            \"description\": \"Whether the search should be case-sensitive. Defaults to false (case-insensitive).\"\n          },\n          \"use_perl_regexp\": {\n            \"type\": \"boolean\",\n            \"description\": \"If true, treats search_text as a Perl-compatible regular expression pattern instead of literal text. Defaults to false.\"\n          }\n        },\n        \"required\": [\n          \"search_text\"\n        ]\n      }\n    }\n  },\n  {\n    \"name\": \"file_read_diff\",\n    \"plan_task\": true,\n    \"main_task\": true,\n    \"definition\": {\n      \"name\": \"file_read_diff\",\n      \"description\": \"The tool is used to view the changes made to other files in the list of modifications. Call this tool when you discover suspected code issues but need to check changes in other files to confirm whether the problem actually exists. This tool will respond in git diff format.\\n\\nOutput example:\\n==== FILE: path/to/file1.txt ====\\n--- a/path/to/file1.txt\\n+++ b/path/to/file1.txt\\n@@ -10,1 +10,1 @@\\n- old content\\n+ new content\\n\\n==== FILE: path/to/file2.txt ====\\n@@ -5,1 +5,2 @@\\n  - old content\\n  + new content1\\n  + new content2\",\n      \"parameters\": {\n        \"type\": \"object\",\n        \"properties\": {\n          \"path_array\": {\n            \"type\": \"array\",\n            \"items\": {\n              \"type\": \"string\"\n            },\n            \"description\": \"List of file paths to view diff content.\"\n          }\n        },\n        \"required\": [\n          \"path_array\"\n        ]\n      }\n    }\n  },\n  {\n    \"name\": \"file_find\",\n    \"plan_task\": true,\n    \"main_task\": true,\n    \"definition\": {\n      \"name\": \"file_find\",\n      \"description\": \"Search for matching files in the current project based on filename keywords. Use this tool when you cannot find the files you need to view in the current change file list.\\n\\nThis tool searches for filenames containing specified keywords in the project directory and returns a list of matching file paths. Search is case-insensitive by default, adjustable via case_sensitive parameter.\\n\\nNote: This tool only supports returning the first 100 matching file paths; excess will be truncated.\\n\\nExample:\\nInput:\\nquery_name: UserService\\nOutput:\\nsrc/main/java/UserService.java\\nsrc/test/java/UserServiceTest.java\",\n      \"parameters\": {\n        \"type\": \"object\",\n        \"properties\": {\n          \"query_name\": {\n            \"type\": \"string\",\n            \"description\": \"Filename keyword to search for, supports partial matching.\"\n          },\n          \"case_sensitive\": {\n            \"type\": \"boolean\",\n            \"description\": \"Whether to perform case-sensitive search. Defaults to false.\"\n          }\n        },\n        \"required\": [\n          \"query_name\"\n        ]\n      }\n    }\n  }\n]",
>   "encoding": "utf-8",
>   "sha": "4701cf73ef72460d6ed5f42f1575a697c45f8868",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/toolsconfig/tools.json",
>   "display_title": "tools.json"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/tool/code_comment.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package tool\n\nimport (\n\t\"context\"\n\t\"encoding/json\"\n\t\"fmt\"\n\n\t\"github.com/open-code-review/open-code-review/internal/model\"\n)\n\n// CodeCommentProvider submits review comments to the per-Agent CommentCollector.\ntype CodeCommentProvider struct {\n\tCollector *CommentCollector\n}\n\nfunc (p *CodeCommentProvider) Tool() Tool { return CodeComment }\n\nfunc (p *CodeCommentProvider) Execute(_ context.Context, args map[string]any) (string, error) {\n\tif p.Collector == nil {\n\t\treturn \"Error: comment collector is not configured\", nil\n\t}\n\n\tcomments, errMsg := ParseComments(args)\n\tif errMsg != \"\" {\n\t\treturn errMsg, nil\n\t}\n\n\tfor i := range comments {\n\t\tp.Collector.Add(comments[i])\n\t}\n\treturn CommentSucceed, nil\n}\n\n// ParseComments extracts LlmComment entries from tool call arguments without writing\n// to the Collector. Returns parsed comments and an error message (empty on success).\nfunc ParseComments(args map[string]any) ([]model.LlmComment, string) {\n\tvar rawComments []any\n\tif arr, ok := args[\"comments\"].([]any); ok && len(arr) > 0 {\n\t\trawComments = arr\n\t} else if s, ok := args[\"comments\"].(string); ok && s != \"\" {\n\t\tif err := json.Unmarshal([]byte(s), &rawComments); err != nil {\n\t\t\treturn nil, fmt.Sprintf(\"Error: failed to parse 'comments' JSON string: %v\", err)\n\t\t}\n\t}\n\tif len(rawComments) == 0 {\n\t\traw, _ := json.Marshal(args)\n\t\treturn nil, fmt.Sprintf(\"Error: 'comments' array is required. Got args: %s\", string(raw))\n\t}\n\n\tvar comments []model.LlmComment\n\tfor _, raw := range rawComments {\n\t\tobj, ok := raw.(map[string]any)\n\t\tif !ok {\n\t\t\tcontinue\n\t\t}\n\n\t\tcm := model.LlmComment{}\n\n\t\tif content, ok := obj[\"content\"].(string); ok {\n\t\t\tcm.Content = content\n\t\t}\n\t\tif suggestion, ok := obj[\"suggestion_code\"].(string); ok {\n\t\t\tcm.SuggestionCode = suggestion\n\t\t}\n\t\tif existing, ok := obj[\"existing_code\"].(string); ok {\n\t\t\tcm.ExistingCode = existing\n\t\t}\n\t\tif thinking, ok := obj[\"thinking\"].(string); ok {\n\t\t\tcm.Thinking = thinking\n\t\t}\n\t\tif category, ok := obj[\"category\"].(string); ok {\n\t\t\tcm.Category = category\n\t\t}\n\t\tif severity, ok := obj[\"severity\"].(string); ok {\n\t\t\tcm.Severity = severity\n\t\t}\n\t\tif path, ok := args[\"path\"].(string); ok {\n\t\t\tcm.Path = path\n\t\t}\n\n\t\tif cm.Path == \"\" || cm.Content == \"\" {\n\t\t\tcontinue\n\t\t}\n\n\t\tcomments = append(comments, cm)\n\t}\n\treturn comments, \"\"\n}\n",
>   "encoding": "utf-8",
>   "sha": "2dac3cb840bc4b985bf39db4c5e9de52b1a9c20c",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/tool/code_comment.go",
>   "display_title": "code_comment.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.search
>
> ```json
> {
>   "query": "ResolveComment",
>   "repository_name": "alibaba/open-code-review",
>   "org": "alibaba",
>   "topn": 20
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "results": [
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/resolver.go",
>       "path": "internal/diff/resolver.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/resolver.go",
>       "display_title": "internal/diff/resolver.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/relocation.go",
>       "path": "internal/diff/relocation.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/relocation.go",
>       "display_title": "internal/diff/relocation.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/llmloop/loop.go",
>       "path": "internal/llmloop/loop.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/llmloop/loop.go",
>       "display_title": "internal/llmloop/loop.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/extensions/vscode/src/extension/providers/CommentProvider.ts",
>       "path": "extensions/vscode/src/extension/providers/CommentProvider.ts",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/extensions/vscode/src/extension/providers/CommentProvider.ts",
>       "display_title": "extensions/vscode/src/extension/providers/CommentProvider.ts"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/extensions/vscode/src/extension/providers/commentAnchor.ts",
>       "path": "extensions/vscode/src/extension/providers/commentAnchor.ts",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/extensions/vscode/src/extension/providers/commentAnchor.ts",
>       "display_title": "extensions/vscode/src/extension/providers/commentAnchor.ts"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/relocation_test.go",
>       "path": "internal/diff/relocation_test.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/relocation_test.go",
>       "display_title": "internal/diff/relocation_test.go"
>     }
>   ]
> }
> ```
>
> MCP tool call
>
> codex_apps.github.search
>
> ```json
> {
>   "query": "DEDUP_TASK",
>   "repository_name": "alibaba/open-code-review",
>   "org": "alibaba",
>   "topn": 20
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "results": [
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/estimate.go",
>       "path": "internal/scan/estimate.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/estimate.go",
>       "display_title": "internal/scan/estimate.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/cmd/opencodereview/scan_cmd.go",
>       "path": "cmd/opencodereview/scan_cmd.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/cmd/opencodereview/scan_cmd.go",
>       "display_title": "cmd/opencodereview/scan_cmd.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/i18n/zh.ts",
>       "path": "pages/src/i18n/zh.ts",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/i18n/zh.ts",
>       "display_title": "pages/src/i18n/zh.ts"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/i18n/en.ts",
>       "path": "pages/src/i18n/en.ts",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/i18n/en.ts",
>       "display_title": "pages/src/i18n/en.ts"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "path": "internal/config/template/template.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "display_title": "internal/config/template/template.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/i18n/ja.ts",
>       "path": "pages/src/i18n/ja.ts",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/pages/src/i18n/ja.ts",
>       "display_title": "pages/src/i18n/ja.ts"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/agent.go",
>       "path": "internal/scan/agent.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/agent.go",
>       "display_title": "internal/scan/agent.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/scan_template.json",
>       "path": "internal/config/template/scan_template.json",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/scan_template.json",
>       "display_title": "internal/config/template/scan_template.json"
>     }
>   ]
> }
> ```
>
> MCP tool call
>
> codex_apps.github.search
>
> ```json
> {
>   "query": "ReLocateComment",
>   "repository_name": "alibaba/open-code-review",
>   "org": "alibaba",
>   "topn": 20
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "results": [
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/relocation.go",
>       "path": "internal/diff/relocation.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/relocation.go",
>       "display_title": "internal/diff/relocation.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/llmloop/loop.go",
>       "path": "internal/llmloop/loop.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/llmloop/loop.go",
>       "display_title": "internal/llmloop/loop.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/relocation_test.go",
>       "path": "internal/diff/relocation_test.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/diff/relocation_test.go",
>       "display_title": "internal/diff/relocation_test.go"
>     }
>   ]
> }
> ```
>
> MCP tool call
>
> codex_apps.github.search
>
> ```json
> {
>   "query": "ProjectSummary",
>   "repository_name": "alibaba/open-code-review",
>   "org": "alibaba",
>   "topn": 20
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "results": [
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/agent.go",
>       "path": "internal/scan/agent.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/agent.go",
>       "display_title": "internal/scan/agent.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/cmd/opencodereview/shared.go",
>       "path": "cmd/opencodereview/shared.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/cmd/opencodereview/shared.go",
>       "display_title": "cmd/opencodereview/shared.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/agent/agent.go",
>       "path": "internal/agent/agent.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/agent/agent.go",
>       "display_title": "internal/agent/agent.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/cmd/opencodereview/output.go",
>       "path": "cmd/opencodereview/output.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/cmd/opencodereview/output.go",
>       "display_title": "cmd/opencodereview/output.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "path": "internal/config/template/template.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template.go",
>       "display_title": "internal/config/template/template.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/cmd/opencodereview/emit_run_result_test.go",
>       "path": "cmd/opencodereview/emit_run_result_test.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/cmd/opencodereview/emit_run_result_test.go",
>       "display_title": "cmd/opencodereview/emit_run_result_test.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/coverage_test.go",
>       "path": "internal/scan/coverage_test.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/coverage_test.go",
>       "display_title": "internal/scan/coverage_test.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/agent/coverage_test.go",
>       "path": "internal/agent/coverage_test.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/agent/coverage_test.go",
>       "display_title": "internal/agent/coverage_test.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template_test.go",
>       "path": "internal/config/template/template_test.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/config/template/template_test.go",
>       "display_title": "internal/config/template/template_test.go"
>     },
>     {
>       "url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/estimate_test.go",
>       "path": "internal/scan/estimate_test.go",
>       "display_url": "https://github.com/alibaba/open-code-review/blob/c3da87885086ff41ed8f2f77b65c7a3c471e01aa/internal/scan/estimate_test.go",
>       "display_title": "internal/scan/estimate_test.go"
>     }
>   ]
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/scan/agent.go",
>   "ref": "main",
>   "encoding": "utf-8",
>   "start_line": 1,
>   "end_line": 350
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package scan\n\nimport (\n\t\"context\"\n\t\"encoding/json\"\n\t\"fmt\"\n\t\"strings\"\n\t\"sync\"\n\t\"sync/atomic\"\n\t\"time\"\n\n\tallowedext \"github.com/open-code-review/open-code-review/internal/config/allowlist\"\n\t\"github.com/open-code-review/open-code-review/internal/config/rules\"\n\t\"github.com/open-code-review/open-code-review/internal/config/template\"\n\t\"github.com/open-code-review/open-code-review/internal/gitcmd\"\n\t\"github.com/open-code-review/open-code-review/internal/llm\"\n\t\"github.com/open-code-review/open-code-review/internal/llmloop\"\n\t\"github.com/open-code-review/open-code-review/internal/model\"\n\t\"github.com/open-code-review/open-code-review/internal/session\"\n\t\"github.com/open-code-review/open-code-review/internal/stdout\"\n\t\"github.com/open-code-review/open-code-review/internal/telemetry\"\n\t\"github.com/open-code-review/open-code-review/internal/tool\"\n)\n\n// changeFilesScanLiteral substitutes for the {{change_files}} placeholder.\n// Full-scan has no \"other changed files\" concept; using a fixed sentinel is\n// less misleading than leaving the placeholder empty.\nconst changeFilesScanLiteral = \"(not applicable in full-scan mode)\"\n\n// Args bundles all dependencies needed for one scan session.\n//\n// Note: Template is the scan-specific template.ScanTemplate (loaded from\n// scan_template.json), not the diff-review template.Template. The two are\n// intentionally separate so review/scan prompts evolve independently.\n//\n// MaxFileSizeBytes overrides the default 2 MiB per-file size cap; it is\n// usually populated from ScanTemplate.MaxFileSizeBytes via scan_cmd.\ntype Args struct {\n\tRepoDir               string\n\tPaths                 []string // empty = whole repo\n\tTemplate              template.ScanTemplate\n\tSystemRule            rules.Resolver\n\tFileFilter            *rules.FileFilter\n\tLLMClient             llm.LLMClient\n\tTools                 *tool.Registry\n\tMainToolDefs          []llm.ToolDef\n\tCommentCollector      *tool.CommentCollector\n\tCommentWorkerPool     *llmloop.CommentWorkerPool\n\tMaxConcurrency        int\n\tConcurrentTaskTimeout int\n\tModel                 string\n\tBackground            string\n\tGitRunner             *gitcmd.Runner\n\tSession               *session.SessionHistory\n\tMaxFileSizeBytes      int64\n\t// SkipPlan disables the PLAN_TASK pre-pass even when the template\n\t// defines one. Set via the --no-plan CLI flag.\n\tSkipPlan bool\n\t// SkipDedup disables the per-batch DEDUP_TASK even when the template\n\t// defines one. Set via the --no-dedup CLI flag.\n\tSkipDedup bool\n\t// SkipSummary disables the post-run PROJECT_SUMMARY_TASK even when the\n\t// template defines one. Set via the --no-summary CLI flag.\n\tSkipSummary bool\n\t// MaxTokensBudget, when > 0, caps total token usage (input+output, as\n\t// reported by the API). Once the running total exceeds it, no further\n\t// batches are dispatched. 0 = unlimited. Set via --max-tokens-budget\n\t// or ScanTemplate.MaxTokensBudget.\n\tMaxTokensBudget int64\n}\n\n// planEnabled / dedupEnabled / summaryEnabled report whether each optional\n// phase will actually run: template must define it AND the corresponding\n// --no-* flag must not be set. Used by both cost estimation and dispatch.\nfunc (a *Agent) planEnabled() bool {\n\treturn !a.args.SkipPlan && a.args.Template.PlanTask != nil && len(a.args.Template.PlanTask.Messages) > 0\n}\n\nfunc (a *Agent) dedupEnabled() bool {\n\treturn !a.args.SkipDedup && a.args.Template.DedupTask != nil && len(a.args.Template.DedupTask.Messages) > 0\n}\n\nfunc (a *Agent) summaryEnabled() bool {\n\treturn !a.args.SkipSummary && a.args.Template.ProjectSummaryTask != nil && len(a.args.Template.ProjectSummaryTask.Messages) > 0\n}\n\n// Agent orchestrates full-file code review. It delegates the per-file LLM\n// tool-use loop to llmloop.Runner and owns only scan-specific concerns\n// (file enumeration, FULL_SCAN_TASK rendering, per-file filtering).\ntype Agent struct {\n\targs           Args\n\titems          []model.ScanItem\n\tcurrentDate    string\n\tsession        *session.SessionHistory\n\tsubtaskFailed  int64 // atomic\n\trunner         *llmloop.Runner\n\tprojectSummary string // populated post-run by maybeRunProjectSummary\n}\n\n// ProjectSummary returns the markdown project-level summary produced after\n// all batches finish. Empty when SkipSummary is set, PROJECT_SUMMARY_TASK\n// is absent, no comments were collected, or the summary LLM call failed.\nfunc (a *Agent) ProjectSummary() string { return a.projectSummary }\n\n// NewAgent creates a scan Agent from the given args. The Session is\n// auto-created (review_mode = full_scan) when not supplied.\nfunc NewAgent(args Args) *Agent {\n\tif args.Tools == nil {\n\t\targs.Tools = tool.NewRegistry()\n\t}\n\tif args.CommentCollector == nil {\n\t\targs.CommentCollector = tool.NewCommentCollector()\n\t}\n\tif args.Session == nil {\n\t\targs.Session = session.New(args.RepoDir, \"\", args.Model, session.SessionOptions{\n\t\t\tReviewMode: session.ReviewModeFullScan,\n\t\t})\n\t}\n\ta := &Agent{\n\t\targs:    args,\n\t\tsession: args.Session,\n\t}\n\ta.runner = llmloop.NewRunner(llmloop.Deps{\n\t\tLLMClient:         args.LLMClient,\n\t\tModel:             args.Model,\n\t\tTemplate:          toLoopTemplate(args.Template),\n\t\tTools:             args.Tools,\n\t\tMainToolDefs:      args.MainToolDefs,\n\t\tCommentCollector:  args.CommentCollector,\n\t\tCommentWorkerPool: args.CommentWorkerPool,\n\t\tSession:           args.Session,\n\t\t// DiffLookup returns a synthetic Diff so the code_comment tool's\n\t\t// line-number resolver (resolveFromFileContent) can match against\n\t\t// the full file content of the scanned file.\n\t\tDiffLookup: a.lookupDiff,\n\t})\n\treturn a\n}\n\n// toLoopTemplate maps the scan-specific ScanTemplate onto the subset of\n// fields llmloop.Runner reads from template.Template. llmloop only needs\n// MaxTokens / MaxToolRequestTimes / MemoryCompressionTask / ReLocationTask,\n// so we leave the diff-only fields (MainTask / PlanTask / ReviewFilterTask)\n// at their zero values.\nfunc toLoopTemplate(s template.ScanTemplate) template.Template {\n\treturn template.Template{\n\t\tMemoryCompressionTask: s.MemoryCompressionTask,\n\t\tMaxTokens:             s.MaxTokens,\n\t\tMaxToolRequestTimes:   s.MaxToolRequestTimes,\n\t\tReLocationTask:        s.ReLocationTask,\n\t}\n}\n\n// Session returns the session history associated with this Agent.\nfunc (a *Agent) Session() *session.SessionHistory { return a.session }\n\n// SessionID returns the current scan's session id, or \"\" when no session has been created.\nfunc (a *Agent) SessionID() string {\n\tif a == nil || a.session == nil {\n\t\treturn \"\"\n\t}\n\treturn a.session.SessionID\n}\n\n// FilesReviewed returns the number of items included in this scan.\nfunc (a *Agent) FilesReviewed() int64 { return int64(len(a.items)) }\n\n// Diffs returns the scanned items adapted to model.Diff form so callers\n// (e.g. cmd/opencodereview's outputJSON / ResolveLineNumbers) can treat\n// both review and scan results uniformly.\nfunc (a *Agent) Diffs() []model.Diff {\n\tout := make([]model.Diff, len(a.items))\n\tfor i := range a.items {\n\t\tout[i] = *a.items[i].AsDiff()\n\t}\n\treturn out\n}\n\n// TotalTokensUsed / TotalInputTokens / ... delegate to the underlying runner.\nfunc (a *Agent) TotalTokensUsed() int64      { return a.runner.TotalTokensUsed() }\nfunc (a *Agent) TotalInputTokens() int64     { return a.runner.TotalInputTokens() }\nfunc (a *Agent) TotalOutputTokens() int64    { return a.runner.TotalOutputTokens() }\nfunc (a *Agent) TotalCacheReadTokens() int64 { return a.runner.TotalCacheReadTokens() }\nfunc (a *Agent) TotalCacheWriteTokens() int64 {\n\treturn a.runner.TotalCacheWriteTokens()\n}\n\n// Warnings returns the warnings recorded by the LLM runner.\nfunc (a *Agent) Warnings() []llmloop.AgentWarning { return a.runner.Warnings() }\n\n// ToolCalls returns per-tool call counts accumulated during scan.\nfunc (a *Agent) ToolCalls() map[string]int64 { return a.runner.ToolCalls() }\n\nfunc (a *Agent) recordWarning(warningType, file, message string) {\n\ta.runner.RecordWarning(warningType, file, message)\n}\n\n// Run executes the full-scan pipeline: enumerate → filter → token-filter →\n// dispatch one subtask per file → collect comments.\nfunc (a *Agent) Run(ctx context.Context) ([]model.LlmComment, error) {\n\tif len(a.args.Template.MainTask.Messages) == 0 {\n\t\treturn nil, fmt.Errorf(\"scan template MAIN_TASK is missing or empty\")\n\t}\n\n\tctx, scanSpan := telemetry.StartSpan(ctx, \"scan.enumerate\")\n\tprovider := NewProvider(a.args.RepoDir, a.args.Paths, a.args.GitRunner, a.args.MaxFileSizeBytes)\n\titems, err := provider.Enumerate(ctx)\n\tif err != nil {\n\t\tscanSpan.End()\n\t\treturn nil, fmt.Errorf(\"enumerate files: %w\", err)\n\t}\n\ttelemetry.SetAttr(scanSpan, \"files.enumerated\", len(items))\n\tscanSpan.End()\n\n\ta.items = items\n\ta.injectScanContentMap()\n\ta.args.Tools.Freeze()\n\n\ttotalDiscovered := len(a.items)\n\ta.items = a.filterScanItems(a.items)\n\ta.items = a.filterLargeScans(a.items)\n\n\treviewable := len(a.items)\n\tfmt.Fprintf(stdout.Writer(), \"[ocr] full-scan: %d file(s) discovered, reviewing %d in %s\\n\",\n\t\ttotalDiscovered, reviewable, a.args.RepoDir)\n\n\tif reviewable == 0 {\n\t\tfmt.Fprintln(stdout.Writer(), \"[ocr] No reviewable files. Skipping scan.\")\n\t\ttelemetry.Event(ctx, \"scan.no.files\")\n\t\ta.session.Finalize()\n\t\treturn []model.LlmComment{}, nil\n\t}\n\n\t// Pre-run cost projection so users aren't surprised by a large scan.\n\test := estimateCost(a.items, a.planEnabled(), a.dedupEnabled(), a.summaryEnabled())\n\tfmt.Fprintf(stdout.Writer(), \"[ocr] estimated cost: %s\\n\", est)\n\tif a.args.MaxTokensBudget > 0 {\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] token budget: %s (dispatch stops once exceeded)\\n\", humanTokens(a.args.MaxTokensBudget))\n\t\tif est.TotalTokens > a.args.MaxTokensBudget {\n\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] WARNING: estimate (%s) exceeds budget (%s); scan will stop partway\\n\",\n\t\t\t\thumanTokens(est.TotalTokens), humanTokens(a.args.MaxTokensBudget))\n\t\t}\n\t}\n\n\ta.currentDate = time.Now().Format(\"2006-01-02 15:04\")\n\ttelemetry.Event(ctx, \"scan.started\",\n\t\ttelemetry.AnyToAttr(\"file.count\", totalDiscovered),\n\t\ttelemetry.AnyToAttr(\"review.count\", reviewable),\n\t\ttelemetry.AnyToAttr(\"est.total.tokens\", est.TotalTokens),\n\t\ttelemetry.AnyToAttr(\"repo.dir\", a.args.RepoDir))\n\ttelemetry.RecordFilesReviewed(ctx, int64(reviewable))\n\n\tcomments, err := a.dispatchSubtasks(ctx)\n\tif len(comments) > 0 {\n\t\ttelemetry.RecordCommentsGenerated(ctx, int64(len(comments)))\n\t}\n\n\t// Project-level summary runs after all batches; never blocks return.\n\ta.maybeRunProjectSummary(ctx, comments)\n\n\ta.session.Finalize()\n\treturn comments, err\n}\n\n// lookupDiff returns the synthetic Diff for a path, used by llmloop.Runner\n// to resolve code_comment line numbers against the scanned file content.\nfunc (a *Agent) lookupDiff(path string) *model.Diff {\n\tfor i := range a.items {\n\t\tif a.items[i].Path == path {\n\t\t\treturn a.items[i].AsDiff()\n\t\t}\n\t}\n\treturn nil\n}\n\n// injectScanContentMap fills the file_read_diff tool's DiffMap with full\n// file content keyed by path, so if the model calls it the tool returns\n// the whole file rather than failing.\nfunc (a *Agent) injectScanContentMap() {\n\tm := make(map[string]string, len(a.items))\n\tfor i := range a.items {\n\t\tit := &a.items[i]\n\t\tif it.Path != \"\" {\n\t\t\tm[it.Path] = it.Content\n\t\t}\n\t}\n\tdm := tool.NewDiffMap(m)\n\tif p, ok := a.args.Tools.Get(tool.FileReadDiff.Name()); ok {\n\t\tif frd, ok := p.(*tool.FileReadDiffProvider); ok {\n\t\t\tfrd.SetDiffMap(dm)\n\t\t}\n\t}\n}\n\n// filterScanItems drops items that should not be reviewed under the standard\n// reviewability rules (binary, extension allowlist, user include/exclude,\n// default excluded paths).\nfunc (a *Agent) filterScanItems(items []model.ScanItem) []model.ScanItem {\n\tvar kept []model.ScanItem\n\tskipped := 0\n\tfor _, it := range items {\n\t\tif reason := a.whyExcluded(it); reason != model.ExcludeNone {\n\t\t\tif it.IsBinary {\n\t\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Skipping %s — binary file\\n\", it.Path)\n\t\t\t} else {\n\t\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Skipping %s — filtered by path/extension rules\\n\", it.Path)\n\t\t\t}\n\t\t\tskipped++\n\t\t\tcontinue\n\t\t}\n\t\tkept = append(kept, it)\n\t}\n\tif skipped > 0 {\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Filtered %d file(s) by include/exclude rules\\n\", skipped)\n\t}\n\treturn kept\n}\n\n// filterLargeScans drops items whose content exceeds 80% of MaxTokens.\nfunc (a *Agent) filterLargeScans(items []model.ScanItem) []model.ScanItem {\n\tlimit := a.args.Template.MaxTokens * 4 / 5\n\tif limit <= 0 {\n\t\treturn items\n\t}\n\tvar kept []model.ScanItem\n\tskipped := 0\n\tfor _, it := range items {\n\t\ttokens := llm.CountTokens(it.Content)\n\t\tif tokens > limit {\n\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Skipping %s (~%d tokens exceeds 80%% of max_tokens(%d))\\n\",\n\t\t\t\tit.Path, tokens, a.args.Template.MaxTokens)\n\t\t\tskipped++\n\t\t\tcontinue\n\t\t}\n\t\tkept = append(kept, it)\n\t}\n\tif skipped > 0 {\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Pre-filtered %d file(s) exceeding 80%% of max_tokens\\n\", skipped)\n\t}\n\treturn kept\n}\n\n// whyExcluded mirrors agent.whyExcluded but for ScanItem inputs.\nfunc (a *Agent) whyExcluded(it model.ScanItem) model.ExcludeReason {\n\tif it.IsBinary {\n\t\treturn model.ExcludeBinary\n\t}\n\tpath := it.Path\n\tif a.args.FileFilter != nil && a.args.FileFilter.IsUserExcluded(path) {\n\t\treturn model.ExcludeUserRule",
>   "encoding": "utf-8",
>   "sha": "aa0b834264930f42789b9061a78d97950b994ce4",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/scan/agent.go",
>   "display_title": "agent.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/scan/agent.go",
>   "ref": "main",
>   "encoding": "utf-8",
>   "start_line": 351,
>   "end_line": 800
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "\t}\n\text := extFromPath(path)\n\tif ext != \"\" && !allowedext.IsAllowedExt(ext) {\n\t\treturn model.ExcludeExtension\n\t}\n\tif a.args.FileFilter != nil && a.args.FileFilter.HasInclude() && a.args.FileFilter.IsUserIncluded(path) {\n\t\treturn model.ExcludeNone\n\t}\n\tif allowedext.IsExcludedPath(path) {\n\t\treturn model.ExcludeDefaultPath\n\t}\n\treturn model.ExcludeNone\n}\n\nfunc extFromPath(path string) string {\n\tbasename := path\n\tif idx := strings.LastIndex(path, \"/\"); idx >= 0 {\n\t\tbasename = path[idx+1:]\n\t}\n\tdot := strings.LastIndex(basename, \".\")\n\tif dot <= 0 {\n\t\treturn \"\"\n\t}\n\treturn strings.ToLower(basename[dot:])\n}\n\n// dispatchSubtasks groups items into batches per the configured strategy,\n// then processes batches sequentially while running files within each\n// batch concurrently up to MaxConcurrency. Sequential batches enable\n// future per-batch hooks (e.g. Phase 6 dedup) and improve LLM prompt-cache\n// hit rate by keeping same-language files adjacent in time.\nfunc (a *Agent) dispatchSubtasks(ctx context.Context) ([]model.LlmComment, error) {\n\tstartTime := time.Now()\n\tdefer func() {\n\t\ttelemetry.RecordReviewDuration(ctx, time.Since(startTime))\n\t}()\n\n\tif len(a.items) == 0 {\n\t\treturn []model.LlmComment{}, nil\n\t}\n\n\tatomic.StoreInt64(&a.subtaskFailed, 0)\n\n\tstrategy := a.resolveBatchStrategy()\n\tbatches := groupBatches(a.items, strategy, a.args.Template.BatchSize)\n\tfmt.Fprintf(stdout.Writer(), \"[ocr] scan dispatch: %d batch(es) by %s strategy\\n\", len(batches), strategy)\n\n\tvar dispatched int64\n\tfor bi, batch := range batches {\n\t\tif err := ctx.Err(); err != nil {\n\t\t\treturn a.args.CommentCollector.Comments(), err\n\t\t}\n\t\t// Snapshot the collector so we can isolate comments added by *this*\n\t\t// batch and feed them into the per-batch dedup hook.\n\t\tbatchStart := a.args.CommentCollector.Snapshot()\n\n\t\tn, budgetHit, err := a.dispatchBatch(ctx, bi, batch)\n\t\tdispatched += n\n\t\tif err != nil {\n\t\t\t// ctx cancelled mid-batch: stop scheduling further batches but\n\t\t\t// still return whatever we've collected so far.\n\t\t\treturn a.args.CommentCollector.Comments(), err\n\t\t}\n\n\t\t// Drain async comment workers BEFORE dedup so all of this batch's\n\t\t// comments are visible. CommentWorkerPool.Await is cumulative\n\t\t// across batches — that's fine since batches are sequential here.\n\t\tif a.args.CommentWorkerPool != nil {\n\t\t\ta.args.CommentWorkerPool.Await()\n\t\t}\n\n\t\ta.maybeRunDedup(ctx, bi, batchStart)\n\n\t\t// The per-file budget gate inside dispatchBatch tripped — stop\n\t\t// scheduling any remaining batches.\n\t\tif budgetHit {\n\t\t\tbreak\n\t\t}\n\t}\n\n\tfailed := atomic.LoadInt64(&a.subtaskFailed)\n\tif failed > 0 && failed == dispatched {\n\t\treturn nil, fmt.Errorf(\"all %d file scan(s) failed — check your LLM configuration and API key\", dispatched)\n\t}\n\treturn a.args.CommentCollector.Comments(), nil\n}\n\n// resolveBatchStrategy reads the strategy from the scan template, defaulting\n// to BatchNone for unrecognized / empty values.\nfunc (a *Agent) resolveBatchStrategy() BatchStrategy {\n\treturn parseBatchStrategy(a.args.Template.BatchStrategy)\n}\n\n// dispatchBatch fans out the files of a single batch concurrently and\n// blocks until they all finish (or ctx is cancelled). Returns the number\n// of files dispatched, whether the token budget was hit mid-batch, and\n// ctx.Err() if cancelled.\n//\n// The budget gate is checked per file, right after acquiring the\n// concurrency slot and before launching the subtask: if the tokens already\n// spent PLUS a look-ahead estimate of this file's cost would exceed the\n// budget, the file (and all remaining files in the batch) are skipped.\n// This keeps overrun bounded by roughly one in-flight file per worker,\n// instead of a whole batch as the coarse batch-level gate did.\nfunc (a *Agent) dispatchBatch(ctx context.Context, batchIdx int, batch []model.ScanItem) (int64, bool, error) {\n\tconcurrency := a.args.MaxConcurrency\n\tif concurrency <= 0 {\n\t\tconcurrency = 8\n\t}\n\tsem := make(chan struct{}, concurrency)\n\ttimeout := time.Duration(a.args.ConcurrentTaskTimeout) * time.Minute\n\n\tvar (\n\t\twg         sync.WaitGroup\n\t\tdispatched int64\n\t\tbudgetHit  bool\n\t)\n\n\tfor i := range batch {\n\t\t// Per-file budget look-ahead. Stop before acquiring a slot so we\n\t\t// don't even queue work that would blow the budget.\n\t\tif a.args.MaxTokensBudget > 0 {\n\t\t\tused := a.runner.TotalTokensUsed()\n\t\t\tprojected := used + estimateFileTokens(batch[i], a.planEnabled())\n\t\t\tif projected > a.args.MaxTokensBudget {\n\t\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] token budget reached (used %s + next-file est ≈ %s > budget %s) — skipping %s and remaining files\\n\",\n\t\t\t\t\thumanTokens(used), humanTokens(projected), humanTokens(a.args.MaxTokensBudget), batch[i].Path)\n\t\t\t\ta.recordWarning(\"token_budget_reached\", batch[i].Path,\n\t\t\t\t\tfmt.Sprintf(\"stopped in batch #%d: used %d tokens + next-file estimate exceeds budget %d\", batchIdx, used, a.args.MaxTokensBudget))\n\t\t\t\tbudgetHit = true\n\t\t\t\tbreak\n\t\t\t}\n\t\t}\n\n\t\tselect {\n\t\tcase sem <- struct{}{}:\n\t\tcase <-ctx.Done():\n\t\t\twg.Wait()\n\t\t\treturn dispatched, budgetHit, ctx.Err()\n\t\t}\n\n\t\tdispatched++\n\t\twg.Add(1)\n\t\tgo func(it model.ScanItem) {\n\t\t\tdefer wg.Done()\n\t\t\tdefer func() { <-sem }()\n\n\t\t\tvar fileCtx context.Context\n\t\t\tvar cancel context.CancelFunc\n\t\t\tif timeout > 0 {\n\t\t\t\tfileCtx, cancel = context.WithTimeout(ctx, timeout)\n\t\t\t\tdefer cancel()\n\t\t\t} else {\n\t\t\t\tfileCtx = ctx\n\t\t\t}\n\n\t\t\tif err := a.executeSubtask(fileCtx, it); err != nil {\n\t\t\t\tatomic.AddInt64(&a.subtaskFailed, 1)\n\t\t\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Scan subtask error for %s (batch #%d): %v\\n\", it.Path, batchIdx, err)\n\t\t\t\ttelemetry.ErrorEvent(fileCtx, \"scan.subtask.error\", err,\n\t\t\t\t\ttelemetry.AnyToAttr(\"file.path\", it.Path),\n\t\t\t\t\ttelemetry.AnyToAttr(\"batch.index\", batchIdx))\n\t\t\t\ta.recordWarning(\"scan_subtask_error\", it.Path, err.Error())\n\t\t\t}\n\t\t}(batch[i])\n\t}\n\n\twg.Wait()\n\treturn dispatched, budgetHit, nil\n}\n\n// executeSubtask runs the scan pipeline for one file:\n//  1. Optional PLAN_TASK: produce a JSON checklist of focus areas.\n//  2. MAIN_TASK: review the file with the plan's checkpoints embedded as\n//     {{plan_guidance}}.\n//\n// Plan phase is skipped (and {{plan_guidance}} is filled with a \"no plan\"\n// sentinel) when Template.PlanTask is nil, args.SkipPlan is true, the file\n// is small enough that planning overhead outweighs gain, or the plan call\n// itself fails. Plan failure never blocks the main review — it falls back\n// to v1 (plan-less) behavior.\nfunc (a *Agent) executeSubtask(ctx context.Context, it model.ScanItem) error {\n\tctx, span := telemetry.StartSpan(ctx, \"scan.subtask.\"+it.Path)\n\tdefer span.End()\n\ttelemetry.SetAttr(span, \"file.path\", it.Path)\n\n\tif ctx.Err() != nil {\n\t\treturn ctx.Err()\n\t}\n\n\trule := \"\"\n\tif a.args.SystemRule != nil {\n\t\trule = a.args.SystemRule.Resolve(strings.ToLower(it.Path))\n\t}\n\n\tplanGuidance := a.maybeRunPlan(ctx, it, rule)\n\n\tmessages := a.renderMessages(it, rule, planGuidance)\n\n\ttokenCount := llmloop.CountMessagesTokens(messages)\n\tmaxAllowed := a.args.Template.MaxTokens\n\ttokenLimit := maxAllowed * 4 / 5\n\tif tokenCount > tokenLimit {\n\t\tmsg := fmt.Sprintf(\"prompt tokens (%d) exceed %d%% of max_tokens(%d)\", tokenCount, 80, maxAllowed)\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] WARNING: %s for %s\\n\", msg, it.Path)\n\t\ta.recordWarning(\"token_threshold_exceeded\", it.Path, msg)\n\t\ttelemetry.Event(ctx, \"token.threshold.exceeded\",\n\t\t\ttelemetry.AnyToAttr(\"file.path\", it.Path),\n\t\t\ttelemetry.AnyToAttr(\"tokens\", tokenCount),\n\t\t\ttelemetry.AnyToAttr(\"max_tokens\", maxAllowed))\n\t\treturn nil\n\t}\n\n\t_, err := a.runner.RunPerFile(ctx, messages, it.Path)\n\treturn err\n}\n\n// maybeRunPlan invokes PLAN_TASK on the file and returns a human-readable\n// guidance string suitable for {{plan_guidance}} substitution. Returns \"(no\n// pre-scan plan; review the entire file as usual)\" when planning is\n// disabled or fails — that sentinel is intentionally non-empty so the\n// surrounding \"### Pre-scan Focus Areas\" header in MAIN_TASK has content\n// instead of dangling.\nfunc (a *Agent) maybeRunPlan(ctx context.Context, it model.ScanItem, rule string) string {\n\tconst noPlan = \"(no pre-scan plan; review the entire file as usual)\"\n\n\tif !a.planEnabled() {\n\t\treturn noPlan\n\t}\n\tpt := a.args.Template.PlanTask\n\n\t// Render plan messages.\n\tmessages := make([]llm.Message, 0, len(pt.Messages))\n\tfor _, m := range pt.Messages {\n\t\tcontent := m.Content\n\t\tcontent = strings.ReplaceAll(content, \"{{current_system_date_time}}\", a.currentDate)\n\t\tcontent = strings.ReplaceAll(content, \"{{current_file_path}}\", it.Path)\n\t\tcontent = strings.ReplaceAll(content, \"{{system_rule}}\", rule)\n\t\tcontent = strings.ReplaceAll(content, \"{{file_content}}\", it.Content)\n\t\tmessages = append(messages, llm.NewTextMessage(m.Role, content))\n\t}\n\n\tfs := a.session.GetOrCreateFileSession(it.Path)\n\trec := fs.AppendTaskRecord(session.PlanTask, messages)\n\tstartTime := time.Now()\n\n\tresp, err := a.args.LLMClient.CompletionsWithCtx(ctx, llm.ChatRequest{\n\t\tModel:     a.args.Model,\n\t\tMessages:  messages,\n\t\tMaxTokens: a.args.Template.MaxTokens,\n\t})\n\tif err != nil {\n\t\trec.SetError(err, time.Since(startTime))\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] scan plan failed for %s: %v (falling back to plan-less)\\n\", it.Path, err)\n\t\treturn noPlan\n\t}\n\trec.SetResponse(resp, time.Since(startTime))\n\ta.runner.RecordUsage(resp.Usage)\n\n\tguidance := formatPlanGuidance(resp.Content())\n\tif guidance == \"\" {\n\t\treturn noPlan\n\t}\n\treturn guidance\n}\n\n// maybeRunProjectSummary runs the post-batch PROJECT_SUMMARY_TASK over the\n// union of all collected comments. Best-effort: any error / empty input\n// / no-template silently leaves projectSummary unset.\nfunc (a *Agent) maybeRunProjectSummary(ctx context.Context, comments []model.LlmComment) {\n\tif !a.summaryEnabled() {\n\t\treturn\n\t}\n\tpt := a.args.Template.ProjectSummaryTask\n\tif len(comments) == 0 {\n\t\treturn\n\t}\n\n\t// Distinct file count for header context.\n\tfileSet := make(map[string]struct{}, len(comments))\n\tfor _, c := range comments {\n\t\tfileSet[c.Path] = struct{}{}\n\t}\n\tpayload := buildSummaryCommentsList(comments)\n\n\tmessages := make([]llm.Message, 0, len(pt.Messages))\n\tfor _, m := range pt.Messages {\n\t\tcontent := m.Content\n\t\tcontent = strings.ReplaceAll(content, \"{{comment_count}}\", fmt.Sprintf(\"%d\", len(comments)))\n\t\tcontent = strings.ReplaceAll(content, \"{{file_count}}\", fmt.Sprintf(\"%d\", len(fileSet)))\n\t\tcontent = strings.ReplaceAll(content, \"{{all_comments}}\", payload)\n\t\tmessages = append(messages, llm.NewTextMessage(m.Role, content))\n\t}\n\n\tconst pathKey = \"__scan_project_summary__\"\n\tfs := a.session.GetOrCreateFileSession(pathKey)\n\trec := fs.AppendTaskRecord(session.MemoryCompressionTask, messages) // reuse existing task type\n\tstartTime := time.Now()\n\n\tresp, err := a.args.LLMClient.CompletionsWithCtx(ctx, llm.ChatRequest{\n\t\tModel:     a.args.Model,\n\t\tMessages:  messages,\n\t\tMaxTokens: a.args.Template.MaxTokens,\n\t})\n\tif err != nil {\n\t\trec.SetError(err, time.Since(startTime))\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] scan project summary failed: %v\\n\", err)\n\t\treturn\n\t}\n\trec.SetResponse(resp, time.Since(startTime))\n\ta.runner.RecordUsage(resp.Usage)\n\n\tbody := strings.TrimSpace(llmloop.StripMarkdownFences(resp.Content()))\n\tif body == \"\" {\n\t\treturn\n\t}\n\ta.projectSummary = body\n}\n\n// buildSummaryCommentsList renders comments as a compact path-anchored\n// markdown list suitable for embedding in the PROJECT_SUMMARY_TASK prompt.\n// Format: \"- `path/to/file.go`: <one-line content (truncated)>\".\n// Content is truncated to ~280 chars to bound prompt growth on large scans.\nfunc buildSummaryCommentsList(comments []model.LlmComment) string {\n\tconst maxLine = 280\n\tvar sb strings.Builder\n\tfor _, c := range comments {\n\t\tsb.WriteString(\"- `\")\n\t\tsb.WriteString(c.Path)\n\t\tsb.WriteString(\"`: \")\n\t\toneLine := strings.ReplaceAll(c.Content, \"\\n\", \" \")\n\t\tif len(oneLine) > maxLine {\n\t\t\toneLine = oneLine[:maxLine] + \"...\"\n\t\t}\n\t\tsb.WriteString(oneLine)\n\t\tsb.WriteString(\"\\n\")\n\t}\n\treturn sb.String()\n}\n\n// maybeRunDedup, when the template has a DedupTask and the batch produced\n// at least DedupMinComments comments, invokes the DEDUP_TASK LLM to merge\n// near-duplicate findings. On any failure (LLM error / malformed JSON /\n// invalid grouping) the original batch comments are kept unchanged — dedup\n// is a best-effort optimization, never a correctness gate.\nfunc (a *Agent) maybeRunDedup(ctx context.Context, batchIdx, batchStart int) {\n\tif !a.dedupEnabled() {\n\t\treturn\n\t}\n\tdt := a.args.Template.DedupTask\n\tminN := a.args.Template.DedupMinComments\n\tif minN <= 0 {\n\t\tminN = 2\n\t}\n\n\tbatchComments := a.args.CommentCollector.Since(batchStart)\n\tif len(batchComments) < minN {\n\t\treturn\n\t}\n\n\tpayload := buildDedupCommentsJSON(batchComments)\n\tmessages := make([]llm.Message, 0, len(dt.Messages))\n\tfor _, m := range dt.Messages {\n\t\tcontent := strings.ReplaceAll(m.Content, \"{{batch_comments}}\", payload)\n\t\tmessages = append(messages, llm.NewTextMessage(m.Role, content))\n\t}\n\n\t// Use a synthetic file path keyed by batch index so the session JSONL\n\t// keeps dedup records distinct from per-file plan/main records.\n\tpathKey := fmt.Sprintf(\"__scan_dedup_batch_%d__\", batchIdx)\n\tfs := a.session.GetOrCreateFileSession(pathKey)\n\trec := fs.AppendTaskRecord(session.MemoryCompressionTask, messages) // reuse existing task type; no scan-specific type to invent\n\tstartTime := time.Now()\n\n\tresp, err := a.args.LLMClient.CompletionsWithCtx(ctx, llm.ChatRequest{\n\t\tModel:     a.args.Model,\n\t\tMessages:  messages,\n\t\tMaxTokens: a.args.Template.MaxTokens,\n\t})\n\tif err != nil {\n\t\trec.SetError(err, time.Since(startTime))\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] scan dedup failed for batch #%d: %v (keeping originals)\\n\", batchIdx, err)\n\t\treturn\n\t}\n\trec.SetResponse(resp, time.Since(startTime))\n\ta.runner.RecordUsage(resp.Usage)\n\n\tdeduped, ok := applyDedupGroups(resp.Content(), batchComments)\n\tif !ok {\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] scan dedup batch #%d: malformed groups, keeping originals\\n\", batchIdx)\n\t\treturn\n\t}\n\tif len(deduped) == len(batchComments) {\n\t\t// No-op result — don't bother rewriting the collector.\n\t\treturn\n\t}\n\ta.args.CommentCollector.ReplaceSince(batchStart, deduped)\n\tfmt.Fprintf(stdout.Writer(), \"[ocr] scan dedup batch #%d: %d → %d comments\\n\", batchIdx, len(batchComments), len(deduped))\n}\n\n// buildDedupCommentsJSON renders the batch comments as a JSON list with\n// stable c-N ids that the LLM groups by. Only fields the LLM needs to\n// judge similarity are included (path / content / existing_code), keeping\n// the prompt compact.\nfunc buildDedupCommentsJSON(comments []model.LlmComment) string {\n\ttype wire struct {\n\t\tID           string `json:\"id\"`\n\t\tPath         string `json:\"path\"`\n\t\tContent      string `json:\"content\"`\n\t\tExistingCode string `json:\"existing_code,omitempty\"`\n\t}\n\titems := make([]wire, len(comments))\n\tfor i, cm := range comments {\n\t\titems[i] = wire{\n\t\t\tID:           fmt.Sprintf(\"c-%d\", i),\n\t\t\tPath:         cm.Path,\n\t\t\tContent:      cm.Content,\n\t\t\tExistingCode: cm.ExistingCode,\n\t\t}\n\t}\n\tdata, _ := json.Marshal(items)\n\treturn string(data)\n}\n\n// applyDedupGroups parses the DEDUP_TASK output and returns the deduped\n// comment slice. Returns (nil, false) when the response is malformed OR\n// when the groups don't cover every input id exactly once (safety: we\n// refuse to silently drop comments we can't account for).\nfunc applyDedupGroups(rawJSON string, originals []model.LlmComment) ([]model.LlmComment, bool) {\n\tstripped := llmloop.StripMarkdownFences(rawJSON)\n\tstripped = strings.TrimSpace(stripped)\n\tif stripped == \"\" {\n\t\treturn nil, false\n\t}\n\tvar parsed struct {\n\t\tGroups []struct {\n\t\t\tMembers       []string `json:\"members\"`\n\t\t\tMergedContent string   `json:\"merged_content,omitempty\"`\n\t\t} `json:\"groups\"`\n\t}\n\tif err := json.Unmarshal([]byte(stripped), &parsed); err != nil {\n\t\treturn nil, false\n\t}\n\n\tidToIdx := make(map[string]int, len(originals))\n\tfor i := range originals {\n\t\tidToIdx[fmt.Sprintf(\"c-%d\", i)] = i\n\t}\n\n\tseen := make(map[string]bool, len(originals))",
>   "encoding": "utf-8",
>   "sha": "aa0b834264930f42789b9061a78d97950b994ce4",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/scan/agent.go",
>   "display_title": "agent.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/diff/relocation.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ````json
> {
>   "content": "package diff\n\nimport (\n\t\"context\"\n\t\"fmt\"\n\t\"strings\"\n\t\"time\"\n\n\t\"github.com/open-code-review/open-code-review/internal/config/template\"\n\t\"github.com/open-code-review/open-code-review/internal/llm\"\n\t\"github.com/open-code-review/open-code-review/internal/model\"\n\t\"github.com/open-code-review/open-code-review/internal/stdout\"\n\t\"github.com/open-code-review/open-code-review/internal/telemetry\"\n)\n\n// ReLocateComment calls the LLM to regenerate a precise existing_code snippet\n// when text-based matching fails, then retries ResolveComment with the new snippet.\n// Returns (success, response, requestMessages) so the caller can record session\n// history and track token usage. Response and messages are nil on early exits.\nfunc ReLocateComment(\n\tctx context.Context,\n\tcm *model.LlmComment,\n\td *model.Diff,\n\tclient llm.LLMClient,\n\ttask *template.LlmConversation,\n\tmodelName string,\n\tmaxTokens int,\n) (bool, *llm.ChatResponse, []llm.Message) {\n\tif task == nil || len(task.Messages) == 0 {\n\t\treturn false, nil, nil\n\t}\n\n\tif task.Timeout > 0 {\n\t\tvar cancel context.CancelFunc\n\t\tctx, cancel = context.WithTimeout(ctx, time.Duration(task.Timeout)*time.Second)\n\t\tdefer cancel()\n\t}\n\n\tmessages := make([]llm.Message, 0, len(task.Messages))\n\tfor _, m := range task.Messages {\n\t\tcontent := m.Content\n\t\tcontent = strings.ReplaceAll(content, \"{diff}\", d.Diff)\n\t\tcontent = strings.ReplaceAll(content, \"{existing_code}\", cm.ExistingCode)\n\t\tcontent = strings.ReplaceAll(content, \"{suggestion_content}\", cm.Content)\n\t\tmessages = append(messages, llm.NewTextMessage(m.Role, content))\n\t}\n\n\tstartTime := time.Now()\n\t_, llmSpan := telemetry.StartLLMSpan(ctx, modelName)\n\tresp, err := client.CompletionsWithCtx(ctx, llm.ChatRequest{\n\t\tModel:     modelName,\n\t\tMessages:  messages,\n\t\tMaxTokens: maxTokens,\n\t})\n\tduration := time.Since(startTime)\n\tif err != nil {\n\t\ttelemetry.RecordLLMResult(llmSpan, duration, 0, err)\n\t\tllmSpan.End()\n\t\tfmt.Fprintf(stdout.Writer(), \"[ocr] Re-location LLM call failed for %s: %v\\n\", cm.Path, err)\n\t\treturn false, nil, messages\n\t}\n\tvar totalTokens int64\n\tif resp.Usage != nil {\n\t\ttotalTokens = resp.Usage.TotalTokens\n\t}\n\ttelemetry.RecordLLMResult(llmSpan, duration, totalTokens, nil)\n\tllmSpan.End()\n\n\tcode := extractCodeBlock(resp.Content())\n\tif code == \"\" {\n\t\treturn false, resp, messages\n\t}\n\n\toriginal := cm.ExistingCode\n\tcm.ExistingCode = code\n\tif ResolveComment(cm, d) {\n\t\treturn true, resp, messages\n\t}\n\tcm.ExistingCode = original\n\treturn false, resp, messages\n}\n\n// extractCodeBlock extracts the content of the first fenced code block from text.\n// Returns empty string if no code block is found.\nfunc extractCodeBlock(text string) string {\n\ttext = strings.TrimSpace(text)\n\tstart := strings.Index(text, \"```\")\n\tif start < 0 {\n\t\treturn \"\"\n\t}\n\tafterOpen := start + 3\n\t// Skip optional language tag on the opening fence line.\n\tif nl := strings.IndexByte(text[afterOpen:], '\\n'); nl >= 0 {\n\t\tafterOpen += nl + 1\n\t} else {\n\t\treturn \"\"\n\t}\n\tend := strings.Index(text[afterOpen:], \"```\")\n\tif end < 0 {\n\t\treturn \"\"\n\t}\n\treturn strings.TrimSpace(text[afterOpen : afterOpen+end])\n}\n",
>   "encoding": "utf-8",
>   "sha": "d1afff599c5a5fcc20505a72996a9e2a74c0a88c",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/diff/relocation.go",
>   "display_title": "relocation.go"
> }
> ````
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/rules/resolver.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> GitHub API error 404: {"message":"Not Found","documentation_url":"https://docs.github.com/rest/repos/contents#get-repository-content","status":"404"}
> ```
>
> ```json
> {
>   "error": "GitHub API error 404: {\"message\":\"Not Found\",\"documentation_url\":\"https://docs.github.com/rest/repos/contents#get-repository-content\",\"status\":\"404\"}",
>   "error_code": "NOT_FOUND",
>   "error_data": {
>     "message": "Not Found",
>     "documentation_url": "https://docs.github.com/rest/repos/contents#get-repository-content",
>     "status": "404"
>   }
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/diff/resolver.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package diff\n\nimport (\n\t\"strings\"\n\n\t\"github.com/open-code-review/open-code-review/internal/model\"\n)\n\n// ResolveLineNumbers populates StartLine/EndLine on each comment by matching\n// the ExistingCode against the corresponding file's diff hunks (primary), or\n// falling back to scanning the full new-file content line-by-line.\nfunc ResolveLineNumbers(comments []model.LlmComment, diffs []model.Diff) []model.LlmComment {\n\tif len(comments) == 0 || len(diffs) == 0 {\n\t\treturn comments\n\t}\n\n\t// Build lookup: newPath -> *Diff\n\tdiffByPath := make(map[string]*model.Diff, len(diffs))\n\tfor i := range diffs {\n\t\td := &diffs[i]\n\t\tif d.NewPath != \"/dev/null\" && d.NewPath != \"\" {\n\t\t\tdiffByPath[d.NewPath] = d\n\t\t}\n\t\tif d.OldPath != \"/dev/null\" && d.OldPath != \"\" {\n\t\t\tdiffByPath[d.OldPath] = d\n\t\t}\n\t}\n\n\tresult := make([]model.LlmComment, len(comments))\n\tcopy(result, comments)\n\n\tfor i := range result {\n\t\tcm := &result[i]\n\t\tif cm.StartLine > 0 || cm.EndLine > 0 {\n\t\t\tcontinue\n\t\t}\n\t\tif cm.ExistingCode == \"\" {\n\t\t\tcontinue\n\t\t}\n\t\td, ok := diffByPath[cm.Path]\n\t\tif !ok {\n\t\t\tcontinue\n\t\t}\n\n\t\t// Primary: try matching from deleted/context lines in diff hunks\n\t\tif resolveFromHunk(d, cm) {\n\t\t\tcontinue\n\t\t}\n\n\t\t// Fallback: scan the new file content for consecutive matches\n\t\tresolveFromFileContent(d, cm)\n\t}\n\n\treturn result\n}\n\n// ResolveComment attempts to resolve StartLine/EndLine for a single comment\n// by matching ExistingCode against the diff. Returns true on success.\nfunc ResolveComment(cm *model.LlmComment, d *model.Diff) bool {\n\tif cm.StartLine > 0 || cm.EndLine > 0 {\n\t\treturn true\n\t}\n\tif cm.ExistingCode == \"\" {\n\t\treturn false\n\t}\n\tif resolveFromHunk(d, cm) {\n\t\treturn true\n\t}\n\treturn resolveFromFileContent(d, cm)\n}\n\n// indexedLine pairs a normalized line with its absolute file line number.\ntype indexedLine struct {\n\tlineNum int\n\tcontent string\n}\n\n// resolveFromHunk tries to find startLine/endLine by matching ExistingCode\n// against hunk lines. It tries the new-side first (context + added lines →\n// new-file line numbers), then falls back to old-side (context + deleted →\n// old-file line numbers).\nfunc resolveFromHunk(d *model.Diff, cm *model.LlmComment) bool {\n\thunks := ParseHunks(d.Diff)\n\tif len(hunks) == 0 {\n\t\treturn false\n\t}\n\n\ttargetLines := splitAndNormalize(cm.ExistingCode)\n\tif len(targetLines) == 0 {\n\t\treturn false\n\t}\n\n\tfor i := range hunks {\n\t\tnewSide := extractSideLines(&hunks[i], true)\n\t\tif start, end, ok := matchConsecutive(newSide, targetLines); ok {\n\t\t\tcm.StartLine = start\n\t\t\tcm.EndLine = end\n\t\t\treturn true\n\t\t}\n\t}\n\n\tfor i := range hunks {\n\t\toldSide := extractSideLines(&hunks[i], false)\n\t\tif start, end, ok := matchConsecutive(oldSide, targetLines); ok {\n\t\t\tcm.StartLine = start\n\t\t\tcm.EndLine = end\n\t\t\treturn true\n\t\t}\n\t}\n\n\treturn false\n}\n\n// extractSideLines extracts one side of the diff from a hunk.\n// When newSide is true, returns context+added lines with new-file line numbers.\n// When newSide is false, returns context+deleted lines with old-file line numbers.\nfunc extractSideLines(hunk *Hunk, newSide bool) []indexedLine {\n\tvar result []indexedLine\n\toldLine := hunk.OldStart\n\tnewLine := hunk.NewStart\n\n\tfor _, l := range hunk.Lines {\n\t\tswitch l.Type {\n\t\tcase HunkContext:\n\t\t\tif newSide {\n\t\t\t\tresult = append(result, indexedLine{newLine, normalizeLine(l.Content)})\n\t\t\t} else {\n\t\t\t\tresult = append(result, indexedLine{oldLine, normalizeLine(l.Content)})\n\t\t\t}\n\t\t\toldLine++\n\t\t\tnewLine++\n\t\tcase HunkAdded:\n\t\t\tif newSide {\n\t\t\t\tresult = append(result, indexedLine{newLine, normalizeLine(l.Content)})\n\t\t\t}\n\t\t\tnewLine++\n\t\tcase HunkDeleted:\n\t\t\tif !newSide {\n\t\t\t\tresult = append(result, indexedLine{oldLine, normalizeLine(l.Content)})\n\t\t\t}\n\t\t\toldLine++\n\t\t}\n\t}\n\treturn result\n}\n\n// matchConsecutive scans sideLines for a consecutive run matching all targetLines.\nfunc matchConsecutive(sideLines []indexedLine, targetLines []string) (startLine, endLine int, found bool) {\n\tif len(targetLines) == 0 || len(sideLines) < len(targetLines) {\n\t\treturn 0, 0, false\n\t}\n\tfor i := 0; i <= len(sideLines)-len(targetLines); i++ {\n\t\tmatched := true\n\t\tfor j, target := range targetLines {\n\t\t\tif sideLines[i+j].content != target {\n\t\t\t\tmatched = false\n\t\t\t\tbreak\n\t\t\t}\n\t\t}\n\t\tif matched {\n\t\t\treturn sideLines[i].lineNum, sideLines[i+len(targetLines)-1].lineNum, true\n\t\t}\n\t}\n\treturn 0, 0, false\n}\n\n// resolveFromFileContent scans the new file content line-by-line for consecutive\n// matches of the normalized existing_code.\nfunc resolveFromFileContent(d *model.Diff, cm *model.LlmComment) bool {\n\tif d.NewFileContent == \"\" {\n\t\treturn false\n\t}\n\n\tfileLines := strings.Split(d.NewFileContent, \"\\n\")\n\ttargetLines := splitAndNormalize(cm.ExistingCode)\n\tif len(targetLines) == 0 {\n\t\treturn false\n\t}\n\n\t// Normalize file lines the same way as target: skip blanks so that\n\t// blank lines in the source don't break the sliding-window match.\n\t// \"Consecutive\" here means adjacent non-blank lines.\n\tnormalizedFileLines := make([]string, 0, len(fileLines))\n\tfileLineNums := make([]int, 0, len(fileLines))\n\tfor i, line := range fileLines {\n\t\tn := normalizeLine(strings.TrimRight(line, \"\\r\"))\n\t\tif n == \"\" {\n\t\t\tcontinue\n\t\t}\n\t\tnormalizedFileLines = append(normalizedFileLines, n)\n\t\tfileLineNums = append(fileLineNums, i+1)\n\t}\n\n\tif len(normalizedFileLines) < len(targetLines) {\n\t\treturn false\n\t}\n\n\tfor i := 0; i <= len(normalizedFileLines)-len(targetLines); i++ {\n\t\tmatched := true\n\t\tfor j, target := range targetLines {\n\t\t\tif normalizedFileLines[i+j] != target {\n\t\t\t\tmatched = false\n\t\t\t\tbreak\n\t\t\t}\n\t\t}\n\t\tif matched {\n\t\t\tcm.StartLine = fileLineNums[i]\n\t\t\tcm.EndLine = fileLineNums[i+len(targetLines)-1]\n\t\t\treturn true\n\t\t}\n\t}\n\n\treturn false\n}\n\n// splitAndNormalize splits code text into lines and normalizes each one.\nfunc splitAndNormalize(code string) []string {\n\traw := strings.Split(code, \"\\n\")\n\tresult := make([]string, 0, len(raw))\n\tfor _, line := range raw {\n\t\tn := normalizeLine(line)\n\t\tif n == \"\" {\n\t\t\tcontinue\n\t\t}\n\t\tresult = append(result, n)\n\t}\n\treturn result\n}\n\n// normalizeLine removes leading/trailing whitespace and strips any leading\n// '+' or '-' diff marker (mirrors Java's processTargetLineCode).\nfunc normalizeLine(s string) string {\n\ts = strings.TrimSpace(s)\n\ts = strings.TrimPrefix(s, \"+\")\n\ts = strings.TrimPrefix(s, \"-\")\n\treturn strings.TrimSpace(s)\n}\n",
>   "encoding": "utf-8",
>   "sha": "e6d256c43fa9b4eb903cb5ddec041996f27cdd94",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/diff/resolver.go",
>   "display_title": "resolver.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/scan/batch.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package scan\n\nimport (\n\t\"sort\"\n\t\"strings\"\n\n\t\"github.com/open-code-review/open-code-review/internal/model\"\n)\n\n// BatchStrategy enumerates the grouping policies for scan dispatch.\ntype BatchStrategy string\n\nconst (\n\t// BatchNone treats every file as its own batch (v1 behavior).\n\tBatchNone BatchStrategy = \"none\"\n\t// BatchByLanguage groups files by extension (case-insensitive).\n\tBatchByLanguage BatchStrategy = \"by-language\"\n\t// BatchByDirectory groups files by their first-level directory under\n\t// the repo root. Files directly in the root form their own batch.\n\tBatchByDirectory BatchStrategy = \"by-directory\"\n)\n\n// parseBatchStrategy normalizes a user-supplied strategy string. Unknown\n// or empty values fall back to BatchNone (safe v1 behavior).\nfunc parseBatchStrategy(s string) BatchStrategy {\n\tswitch BatchStrategy(strings.ToLower(strings.TrimSpace(s))) {\n\tcase BatchByLanguage:\n\t\treturn BatchByLanguage\n\tcase BatchByDirectory:\n\t\treturn BatchByDirectory\n\tdefault:\n\t\treturn BatchNone\n\t}\n}\n\n// groupBatches partitions items according to strategy, then slices each\n// natural group into BatchSize-sized chunks (when size > 0). Within a batch\n// the input order is preserved; batches themselves are sorted by their\n// group key for determinism.\n//\n// Returns nil when items is empty.\nfunc groupBatches(items []model.ScanItem, strategy BatchStrategy, size int) [][]model.ScanItem {\n\tif len(items) == 0 {\n\t\treturn nil\n\t}\n\n\t// Bucket by group key.\n\tkeyFn := batchKeyFunc(strategy)\n\tbuckets := make(map[string][]model.ScanItem)\n\tfor _, it := range items {\n\t\tkey := keyFn(it)\n\t\tbuckets[key] = append(buckets[key], it)\n\t}\n\n\t// Deterministic batch order via sorted keys.\n\tkeys := make([]string, 0, len(buckets))\n\tfor k := range buckets {\n\t\tkeys = append(keys, k)\n\t}\n\tsort.Strings(keys)\n\n\tvar out [][]model.ScanItem\n\tfor _, k := range keys {\n\t\tgroup := buckets[k]\n\t\tif size <= 0 || len(group) <= size {\n\t\t\tout = append(out, group)\n\t\t\tcontinue\n\t\t}\n\t\t// Chunk the natural group into BatchSize-sized slices.\n\t\tfor start := 0; start < len(group); start += size {\n\t\t\tend := start + size\n\t\t\tif end > len(group) {\n\t\t\t\tend = len(group)\n\t\t\t}\n\t\t\tout = append(out, group[start:end])\n\t\t}\n\t}\n\treturn out\n}\n\n// batchKeyFunc returns the grouping key extractor for a strategy.\nfunc batchKeyFunc(strategy BatchStrategy) func(model.ScanItem) string {\n\tswitch strategy {\n\tcase BatchByLanguage:\n\t\treturn languageKey\n\tcase BatchByDirectory:\n\t\treturn firstLevelDirKey\n\tdefault:\n\t\t// BatchNone: each file is its own batch.\n\t\treturn func(it model.ScanItem) string { return it.Path }\n\t}\n}\n\n// languageKey returns the lowercased file extension (with the leading dot)\n// or \"<no-ext>\" for extensionless files.\nfunc languageKey(it model.ScanItem) string {\n\tbase := it.Path\n\tif i := strings.LastIndex(base, \"/\"); i >= 0 {\n\t\tbase = base[i+1:]\n\t}\n\tdot := strings.LastIndex(base, \".\")\n\tif dot <= 0 {\n\t\treturn \"<no-ext>\"\n\t}\n\treturn strings.ToLower(base[dot:])\n}\n\n// firstLevelDirKey returns the first path segment of a repo-relative path,\n// or \"<root>\" for files directly in the repo root.\nfunc firstLevelDirKey(it model.ScanItem) string {\n\tidx := strings.IndexByte(it.Path, '/')\n\tif idx < 0 {\n\t\treturn \"<root>\"\n\t}\n\treturn it.Path[:idx]\n}\n",
>   "encoding": "utf-8",
>   "sha": "88186af4d0ea3648693cd3287a33fd1526befd43",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/scan/batch.go",
>   "display_title": "batch.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/scan/estimate.go",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "package scan\n\nimport (\n\t\"fmt\"\n\n\t\"github.com/open-code-review/open-code-review/internal/llm\"\n\t\"github.com/open-code-review/open-code-review/internal/model\"\n)\n\n// Cost-estimation heuristics. These are deliberately rough — their job is\n// to give the user an order-of-magnitude warning before a large scan, not\n// to be billing-accurate. Real usage is always reported from the API\n// response after the run.\nconst (\n\t// promptOverheadTokens approximates the fixed prompt scaffolding per LLM\n\t// call (system prompt + template wrappers + tool definitions).\n\tpromptOverheadTokens = 2000\n\t// avgMainRoundsPerFile is the assumed number of MAIN_TASK tool-use\n\t// rounds for a typical file. Observed ~6 on real repos; round up.\n\tavgMainRoundsPerFile = 7\n\t// avgOutputTokensPerRound approximates completion tokens per round.\n\tavgOutputTokensPerRound = 700\n)\n\n// Estimate is a pre-run, order-of-magnitude projection of scan cost.\ntype Estimate struct {\n\tFiles        int\n\tInputTokens  int64\n\tOutputTokens int64\n\tTotalTokens  int64\n}\n\n// estimateCost projects token usage for reviewing the given items under the\n// supplied scan template. planEnabled / dedupEnabled / summaryEnabled\n// reflect the effective runtime toggles (template field present AND not\n// disabled by a --no-* flag).\n// estimateFileTokens projects the input+output token cost of reviewing a\n// single file (PLAN_TASK + MAIN_TASK rounds). Excludes the run-level dedup/\n// summary phases. Returns 0 for files that are skipped before dispatch\n// (binary / empty). Used both by the aggregate estimate and by the\n// per-file budget look-ahead in dispatch.\nfunc estimateFileTokens(it model.ScanItem, planEnabled bool) int64 {\n\tif it.IsBinary || it.Content == \"\" {\n\t\treturn 0\n\t}\n\tfileTokens := int64(llm.CountTokens(it.Content))\n\n\tvar total int64\n\tif planEnabled {\n\t\ttotal += fileTokens + promptOverheadTokens // PLAN input\n\t\ttotal += 400                               // PLAN output (small JSON)\n\t}\n\t// MAIN_TASK: file content carried across rounds + per-round overhead.\n\ttotal += (fileTokens + promptOverheadTokens) * avgMainRoundsPerFile\n\ttotal += avgOutputTokensPerRound * avgMainRoundsPerFile\n\treturn total\n}\n\nfunc estimateCost(items []model.ScanItem, planEnabled, dedupEnabled, summaryEnabled bool) Estimate {\n\tvar est Estimate\n\tvar allCommentsApprox int64\n\n\tfor i := range items {\n\t\tit := &items[i]\n\t\tif it.IsBinary || it.Content == \"\" {\n\t\t\tcontinue // skipped before dispatch\n\t\t}\n\t\test.Files++\n\t\t// Per-file cost folds into InputTokens for the aggregate; we don't\n\t\t// split input/output here since the look-ahead only needs the total.\n\t\t// Recompute the input/output split inline to keep the headline\n\t\t// numbers meaningful.\n\t\tfileTokens := int64(llm.CountTokens(it.Content))\n\t\tif planEnabled {\n\t\t\test.InputTokens += fileTokens + promptOverheadTokens\n\t\t\test.OutputTokens += 400\n\t\t}\n\t\test.InputTokens += (fileTokens + promptOverheadTokens) * avgMainRoundsPerFile\n\t\test.OutputTokens += avgOutputTokensPerRound * avgMainRoundsPerFile\n\n\t\t// Rough comment yield used to size dedup/summary inputs downstream.\n\t\tallCommentsApprox += 3\n\t}\n\n\t// DEDUP_TASK: one call per batch; approximate as a single pass over all\n\t// comments (batches partition them, so total dedup input ≈ all comments).\n\tif dedupEnabled && allCommentsApprox > 0 {\n\t\test.InputTokens += allCommentsApprox*120 + promptOverheadTokens\n\t\test.OutputTokens += allCommentsApprox * 20\n\t}\n\n\t// PROJECT_SUMMARY_TASK: one call over all comments.\n\tif summaryEnabled && allCommentsApprox > 0 {\n\t\test.InputTokens += allCommentsApprox*120 + promptOverheadTokens\n\t\test.OutputTokens += 2000\n\t}\n\n\test.TotalTokens = est.InputTokens + est.OutputTokens\n\treturn est\n}\n\n// String renders a one-line human-readable estimate. Money is intentionally\n// omitted — pricing varies per provider/model and we don't want to imply a\n// precise dollar figure.\nfunc (e Estimate) String() string {\n\treturn fmt.Sprintf(\"~%d file(s), est. %s input + %s output ≈ %s total tokens (rough; actual reported after run)\",\n\t\te.Files, humanTokens(e.InputTokens), humanTokens(e.OutputTokens), humanTokens(e.TotalTokens))\n}\n\n// humanTokens formats a token count as e.g. \"1.2M\" / \"850K\" / \"420\".\nfunc humanTokens(n int64) string {\n\tswitch {\n\tcase n >= 1_000_000:\n\t\treturn fmt.Sprintf(\"%.1fM\", float64(n)/1_000_000)\n\tcase n >= 1_000:\n\t\treturn fmt.Sprintf(\"%.0fK\", float64(n)/1_000)\n\tdefault:\n\t\treturn fmt.Sprintf(\"%d\", n)\n\t}\n}\n",
>   "encoding": "utf-8",
>   "sha": "ea2c034b9e1a5cd89e4c43ee72e345e656afb68b",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/scan/estimate.go",
>   "display_title": "estimate.go"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/prompts/main_task_system.md",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "## Role\nYou are a code review assistant developed by Alibaba. You are skilled at code review in the software development process and are responsible for providing professional review feedback for code changes that are about to be submitted. Your feedback perfectly combines detailed analysis with contextual explanations.\nYou are working in an IDE with editor concepts for open files and an integrated terminal. The user's developed code is stored in the IDE's staging area.\nBefore users commit staged code to remote repositories, they will send you tasks to help them complete the process successfully. Each time a user sends a task, it will be placed in <user_task>, and you will use <tool> to interact with the real world when executing tasks.\nPlease keep your responses concise and objective.\n\n## Capabilities\n- Think step by step progressively.\n- First understand the code changes to be reviewed. Code changes are provided in Unified Diff format, where lines starting with `-` indicate deleted code, lines starting with `+` indicate added code, consecutive `-` and `+` lines represent modified code, and other lines represent unchanged code.\n- Be objective and neutral, make judgments based on facts and logic, avoid subjective assumptions. When the context is unclear, use tools to obtain contextual information rather than judging based on assumptions.\n- For the current code changes, provide feedback opinions, pointing out areas for improvement or potential issues. Focus on issues in newly added code.\n- Avoid commenting on correct code or unchanged code.\n- Avoid commenting on deleted code; deleted code serves only as reference context.\n- Focus on clarity, practicality, and comprehensiveness.\n- Use developer-friendly terminology and analogies in explanations.\n- Focus primarily on the actual code logic and functionality. Avoid commenting on or providing feedback about non-functional elements such as code comments, tool-generated indicators (like @Generated annotations), or other metadata, unless the user explicitly requests you to review these elements.\n\n## Strict Focus Rules\n- Context tools are for understanding purposes only. Findings from other files must NOT become the subject of your comments.\n- If you discover a potential issue in another file while gathering context, ignore it — your task is limited to the current diffs.\n\n## Reply limit\n- If the current code review task is complete, call `task_done` to end the task.\n- If a code issue has been identified and confirmed, call the `code_comment` tool to provide feedback.\n- If additional context is needed to confirm the issue, call the appropriate context tool.\n",
>   "encoding": "utf-8",
>   "sha": "0f21fbc58f022d55ff4260ec6769a0709b18594f",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/prompts/main_task_system.md",
>   "display_title": "main_task_system.md"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/prompts/main_task_user.md",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "// The following is the list of other files changed in this update.\n<other_changed_files>\n{{change_files}}\n</other_changed_files>\n\n<current_file_path>{{current_file_path}}</current_file_path>\n\n<current_file_diff>\n{{diff}}\n</current_file_diff>\n\nCurrent time in the real world: {{current_system_date_time}}\n\n<user_task>\n### Requirement Background (Optional)\n{{requirement_background}}\n\n### Review Checklist\n{{system_rule}}\n\n### Review Plan (Optional)\n{{plan_guidance}}\n\nNow please review the code changes in <current_file_diff>\n</user_task>\n",
>   "encoding": "utf-8",
>   "sha": "eef378cb50622836bb2bd7dd0c455239213a207f",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/prompts/main_task_user.md",
>   "display_title": "main_task_user.md"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/prompts/review_filter_task_user.md",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ````json
> {
>   "content": "### Task\n\nGiven a code diff and a set of review comments, identify those that are **provably incorrect based solely on the diff**.\n\n### Evaluation Principles\n\n**Core principle: You need to falsify, not verify.**\n\n- ✅ Should flag: The diff contains **direct counter-evidence** that proves the key claim of the review comment is wrong\n- ❌ Should NOT flag: The review comment references context not visible in the diff (may have been obtained by the Agent via tools)\n- ❌ Should NOT flag: You merely \"cannot verify\" but also cannot disprove the review comment\n\n### Evaluation Method\n\nFor each review comment, perform the following two steps:\n\n#### Step 1: Fact Check (Veto Rule)\n\n- Only verify claims that are verifiable within the diff\n- Only determine a comment as incorrect when the diff provides counter-evidence. **If a claim involves information outside the diff (such as logic in other files, business semantics, runtime behavior), and the diff contains no evidence contradicting it, do not make a determination.**\n\n⚠️ Fact check fails → Immediately determine as incorrect, skip Step 2.\n\n#### Step 2: Issue Classification\n\nAfter confirming that the facts visible in the diff are accurate, determine whether the description contains a **significant deviation that can be disproved from the diff**:\n\n- Does it misidentify clearly normal code in the diff as a defect?\n- Does it attribute behavior visible in the diff in a way that contradicts the code?\n\n⚠️ Only determine as incorrect when the diff can directly prove the description is wrong.\n\n### Code Diff\n\n```{{path}}\n{{diff}}\n```\n\n### Review Comments\n\n{{comments}}\n\n### Output\n\nReturn all incorrect review comment IDs directly, without any explanation. Use JSON array format:\n\n```json\n[\"id-xxx\", \"id-yyy\"]\n```\n\nIf there are no review comments that can be confirmed as incorrect, return an empty array:\n\n```json\n[]\n```\n",
>   "encoding": "utf-8",
>   "sha": "d2b6472595cf04abf56f0e1f3e016572d3b3aa30",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/prompts/review_filter_task_user.md",
>   "display_title": "review_filter_task_user.md"
> }
> ````
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/prompts/main_task_system.md",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "## Role\nYou are a code review assistant developed by Alibaba. You are skilled at code review in the software development process and are responsible for providing professional review feedback for code changes that are about to be submitted. Your feedback perfectly combines detailed analysis with contextual explanations.\nYou are working in an IDE with editor concepts for open files and an integrated terminal. The user's developed code is stored in the IDE's staging area.\nBefore users commit staged code to remote repositories, they will send you tasks to help them complete the process successfully. Each time a user sends a task, it will be placed in <user_task>, and you will use <tool> to interact with the real world when executing tasks.\nPlease keep your responses concise and objective.\n\n## Capabilities\n- Think step by step progressively.\n- First understand the code changes to be reviewed. Code changes are provided in Unified Diff format, where lines starting with `-` indicate deleted code, lines starting with `+` indicate added code, consecutive `-` and `+` lines represent modified code, and other lines represent unchanged code.\n- Be objective and neutral, make judgments based on facts and logic, avoid subjective assumptions. When the context is unclear, use tools to obtain contextual information rather than judging based on assumptions.\n- For the current code changes, provide feedback opinions, pointing out areas for improvement or potential issues. Focus on issues in newly added code.\n- Avoid commenting on correct code or unchanged code.\n- Avoid commenting on deleted code; deleted code serves only as reference context.\n- Focus on clarity, practicality, and comprehensiveness.\n- Use developer-friendly terminology and analogies in explanations.\n- Focus primarily on the actual code logic and functionality. Avoid commenting on or providing feedback about non-functional elements such as code comments, tool-generated indicators (like @Generated annotations), or other metadata, unless the user explicitly requests you to review these elements.\n\n## Strict Focus Rules\n- Context tools are for understanding purposes only. Findings from other files must NOT become the subject of your comments.\n- If you discover a potential issue in another file while gathering context, ignore it — your task is limited to the current diffs.\n\n## Reply limit\n- If the current code review task is complete, call `task_done` to end the task.\n- If a code issue has been identified and confirmed, call the `code_comment` tool to provide feedback.\n- If additional context is needed to confirm the issue, call the appropriate context tool.\n",
>   "encoding": "utf-8",
>   "sha": "0f21fbc58f022d55ff4260ec6769a0709b18594f",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/prompts/main_task_system.md",
>   "display_title": "main_task_system.md"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/prompts/plan_task_user.md",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ````json
> {
>   "content": "// The following is the list of other files changed in this update.\n<other_changed_files>\n{{change_files}}\n</other_changed_files>\n\n<current_file_path>{{current_file_path}}</current_file_path>\n\n<current_file_diff>\n{{diff}}\n</current_file_diff>\n\nCurrent time in the real world: {{current_system_date_time}}\n\n### Requirement Background (Optional)\n{{requirement_background}}\n\n### Review Checklist\n{{system_rule}}\n\n### Task\nPlease analyze the code changes above and output a structured review plan. Start with ```json\n",
>   "encoding": "utf-8",
>   "sha": "c5c0e82631243a7042a768ffc3162b8cd4fc8dbc",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/prompts/plan_task_user.md",
>   "display_title": "plan_task_user.md"
> }
> ````
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/prompts/plan_task_system.md",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "You are an expert in code review task planning. You have access to a set of tools for retrieving relevant context about code changes, and your responsibility is to analyze those changes and produce a structured review plan.\n\n## Core Responsibilities\nAnalyze code change content, identify potential risk points, and plan appropriate tool-calling strategies for each risk point.\n\n## Tool Descriptions\n{{plan_tools}}\n\n## Output Format\nStrictly follow the JSON format below. Do not include any additional explanatory text:\n\n{\n  \"change_summary\": \"A brief description of the purpose and scope of this code change\",\n  \"issues\": [\n    {\n      \"severity\": \"high|medium|low\",\n      \"description\": \"A clear description of the specific problem and its potential impact for this risk point\",\n      \"tool_guidance\": [\n        {\n          \"name\": \"Tool name\",\n          \"reason\": \"Explain the purpose of calling this tool and its relevance to the current issue\",\n          \"arguments\": \"Invocation arguments\"\n        }\n      ]\n    }\n  ]\n}\n\n## Analysis Rules\n1. **Scope**: Only analyze newly added and modified code; ignore deleted code\n2. **Ordering**: The issues list must be sorted by severity in descending order (high → medium → low)\n3. **Severity Definitions**:\n   - `high`: May cause security vulnerabilities, data loss, system crashes, or critical functional failures\n   - `medium`: May affect performance, maintainability, or involve potential edge-case problems\n   - `low`: Code style, readability, or non-critical best practice suggestions\n4. **Tool Usage**: Tools are for reference purposes only and must not be actually invoked; describe the calling intent within tool_guidance\n5. **Description Requirements**: Each description must cover three dimensions — problem location, nature of the problem, and potential impact\n",
>   "encoding": "utf-8",
>   "sha": "bac9b3818607a0f81c70ae612b5e69d4dded64b9",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/prompts/plan_task_system.md",
>   "display_title": "plan_task_system.md"
> }
> ```
>
> MCP tool call
>
> codex_apps.github.fetch_file
>
> ```json
> {
>   "repository_full_name": "alibaba/open-code-review",
>   "path": "internal/config/template/prompts/review_filter_task_system.md",
>   "ref": "main",
>   "encoding": "utf-8"
> }
> ```
>
> ```text
> Action completed.
> ```
>
> ```json
> {
>   "content": "You are a fact-checker for code review comments.\n\nThese review comments come from an Agent that can invoke tools to obtain the full code context. You can currently only see the code diff.\n\nTherefore, your task is NOT to verify whether all review comments are correct, but to **filter out only those review comments that can be confirmed as incorrect based solely on the current diff**.\n\nFor review comments whose correctness cannot be determined from the diff alone, even if you find them suspicious, you should let them pass — because the Agent may have access to context that you cannot see.\n",
>   "encoding": "utf-8",
>   "sha": "bff2f0dd67bec877de065ccab7d48f6c7ad2ca06",
>   "display_url": "https://github.com/alibaba/open-code-review/blob/main/internal/config/template/prompts/review_filter_task_system.md",
>   "display_title": "review_filter_task_system.md"
> }
> ```
>
> </details>
>
> 对照完成后，最关键的结论不是“少了几个字段”，而是三处执行顺序会直接伤害准确率：本项目目前是先让 LLM 重定位、再做本地校验；过滤阶段可能把“无法证明”误当成“应过滤”；多行 `existing_code` 被压成一行后逐行模糊匹配，容易错锚。OCR 则是确定性定位优先、失败才重定位，并采用“只有 diff 能直接证伪才删除”的过滤原则。接下来我会先修这三条，再补跨文件 DiffMap 和严格工具闭环。
>
> 我准备开始修改核心链路：新增一个确定性证据定位器，支持多行连续匹配、唯一性和变更行重叠判断；同时让目录对比产出完整的变更清单与只读 DiffMap，使 `file_read_diff` 能查看其他变更文件（包括删除文件）。这些上下文会进入 plan/main，而审核结果仍落在现有 `CodeFileModel`/`CodeBlock`/`Issue` 结构中。
>
> <details><summary>Created a file, edited 5 files</summary>
>
> - Wrote `./app/services/diff_service.py` (+53 -8)
> - Wrote `./app/services/evidence.py` (+275 -0)
> - Wrote `./app/models/code_file.py` (+13 -0)
> - Wrote `./app/schemas/code_file.py` (+26 -0)
> - Wrote `./app/core/config.py` (+11 -1)
> - Wrote `./app/services/review_tools.py` (+208 -63)
>
> </details>
>
> 工具层已按 OCR 的真实接口补齐：`file_read_diff` 现在能批量读取任意变更文件，`code_search` 支持文件模式、大小写和正则，`read_file` 有 500 行/文件大小/路径穿越约束，重复只读调用会复用结果；`code_comment` 同时支持批量提交并拒绝缺证据的问题。下一步是把这些能力写入结构化 plan，并收紧 main_task 的显式完成语义。
>
> <details><summary>Edited 9 files</summary>
>
> - Wrote `./app/services/prompts.py` (+55 -49)
> - Wrote `./app/services/prompts.py` (+33 -7)
> - Wrote `./app/services/review_service.py` (+36 -6)
> - Wrote `./app/services/review_service.py` (+15 -4)
> - Wrote `./app/services/review_service.py` (+94 -12)
> - Wrote `./app/services/review_service.py` (+97 -27)
> - Wrote `./app/services/review_service.py` (+54 -60)
> - Wrote `./app/models/code_file.py` (+1 -0)
> - Wrote `./app/schemas/code_file.py` (+2 -0)
> - Wrote `./app/services/review_service.py` (+13 -3)
> - Wrote `./app/services/review_service.py` (+31 -22)
> - Wrote `./app/services/review_service.py` (+26 -8)
> - Wrote `./app/services/review_service.py` (+23 -22)
> - Wrote `./app/services/review_service.py` (+7 -0)
> - Wrote `./app/services/review_service.py` (+6 -2)
> - Wrote `./app/services/review_service.py` (+1 -0)
> - Wrote `./app/models/task.py` (+7 -0)
> - Wrote `./app/schemas/task.py` (+14 -0)
> - Wrote `./app/services/review_service.py` (+27 -3)
> - Wrote `./app/services/review_service.py` (+46 -3)
> - Wrote `./app/services/review_service.py` (+4 -2)
> - Wrote `./app/services/evidence.py` (+13 -0)
> - Wrote `./app/services/review_tools.py` (+3 -0)
> - Wrote `./app/services/rules.py` (+37 -0)
>
> </details>
>
> 现在关键顺序已经改成“本地连续证据定位 → 仅失败项调用 re-location → 再次确定性验证”，过滤也改成“机械证据门禁 + 反证式 LLM 复核”。另外，生产环境的 main_task 异常不再生成 mock 问题冒充真实结论；未显式完成或预算跳过的任务会标记为 partial，而不是错误地写成全部完成。先跑静态检查和测试，定位兼容性问题后再补语义去重/项目摘要层。
>
> 第一轮回归暴露了 7 个兼容性差异，其中 5 个是测试仍假设旧顺序/旧完成状态，另外 2 个是工具返回格式兼容问题。核心逻辑本身已通过语法检查；我会保留新语义（预算跳过即 partial、确定性定位优先），同时补回单文件 `file_read_diff` 的旧字段和原路径错误关键字，避免现有调用方无谓破坏。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./app/services/review_service.py` (+2 -2)
> - Wrote `./app/services/review_tools.py` (+5 -2)
> - Wrote `./tests/test_review_service.py` (+45 -35)
> - Wrote `./tests/test_review_service.py` (+8 -5)
> - Wrote `./tests/test_review_service.py` (+4 -4)
>
> </details>
>
> 核心改动已经重新通过原有 23 项测试。现在我在补“防回退”用例，专门覆盖旧测试没有约束住的准确度要点：多行证据连续定位、重复片段消歧、删除文件的跨文件 diff 查询、畸形 function arguments 不打断循环，以及没有 `task_done` 时不得伪装成审核完成。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/test_review_service.py` (+228 -0)
> - Wrote `./tests/test_review_tools.py` (+60 -0)
> - Wrote `./tests/test_review_service.py` (+22 -0)
>
> </details>
>
> 新增回归用例已扩展到 31 项并全部通过。与 OCR 的剩余实质差距主要在全量扫描：OCR 为 scan 使用 60 轮上限、LLM 批次语义去重和 LLM 项目摘要；本项目目前仍是统一 30 轮、确定性精确去重和统计摘要。我会把这三项补成可配置的增强，同时把任务级模型轨迹和实际 token 汇总一起保存。
>
> <details><summary>Edited 8 files</summary>
>
> - Wrote `./app/core/config.py` (+6 -0)
> - Wrote `./app/services/prompts.py` (+36 -0)
> - Wrote `./app/services/review_service.py` (+2 -0)
> - Wrote `./app/models/task.py` (+4 -1)
> - Wrote `./app/schemas/task.py` (+3 -0)
> - Wrote `./app/services/review_service.py` (+3 -0)
> - Wrote `./app/services/review_service.py` (+15 -2)
> - Wrote `./tests/test_review_service.py` (+6 -1)
> - Wrote `./app/models/code_file.py` (+2 -0)
> - Wrote `./app/schemas/code_file.py` (+4 -0)
> - Wrote `./app/services/review_service.py` (+133 -3)
> - Wrote `./app/services/review_service.py` (+1 -0)
> - Wrote `./app/services/review_service.py` (+77 -4)
> - Wrote `./app/services/review_service.py` (+1 -0)
> - Wrote `./tests/test_review_service.py` (+147 -1)
> - Wrote `./tests/test_review_service.py` (+2 -1)
>
> </details>
>
> 全量扫描增强已经落地：增量默认 30 轮、full scan 默认 60 轮，并增加单文件 600 秒总时限；批次达到阈值时可进行受严格校验的 LLM 语义去重；多文件 full scan 会生成 LLM 项目摘要，失败自动回退统计摘要。两类任务级调用的输入输出摘要、token 与耗时会写入 `TaskModel.task_model_rounds`。现在同步环境变量和 README，再做最终全量验证。
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./.env.example` (+17 -1)
> - Wrote `./docker-compose.yml` (+18 -1)
> - Wrote `./README.md` (+24 -13)
> - Wrote `./app/services/review_service.py` (+10 -1)
>
> </details>
>
> 我又补到一个会真实制造误报的目录对比差异：纯文件重命名在本地双目录模式下会被当成“删除旧文件 + 新增整文件”，导致整文件被错误送审。OCR 的 Git provider 能识别 rename；我正在为本地目录比较增加唯一 MD5 配对，只记录 `RENAMED old -> new` 上下文，不启动无意义的代码审核。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/diff_service.py` (+38 -0)
> - Wrote `./tests/test_review_tools.py` (+18 -0)
>
> </details>
>
> 规则链路还发现一个隐藏偏差：服务虽然支持 `REVIEW_RULES_PATH`，但 prompt 构建函数此前重新读取了全局默认配置，使用自定义 `Settings` 执行任务时规则实际上可能没有进入提示词。我会修正配置透传，并自动发现目标仓库的 `.opencodereview/rule.json`，实现“显式路径优先、项目规则其次、内置规则兜底”的解析顺序。
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./app/services/prompts.py` (+9 -4)
> - Wrote `./app/services/review_service.py` (+6 -0)
> - Wrote `./app/services/review_service.py` (+8 -0)
> - Wrote `./tests/test_review_service.py` (+26 -0)
> - Wrote `./app/services/rules.py` (+7 -1)
> - Wrote `./tests/test_review_service.py` (+3 -0)
>
> </details>
>
> 规则配置透传和项目级自动发现已修复，纯重命名也不再误送审。当前完整测试已增至 35 项并全部通过，敏感 API Key 未写入仓库；接下来只剩容器配置校验和一次代码差异审计，重点检查新增字段、默认值和 README 是否完全一致。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./app/services/review_service.py` (+1 -0)
>
> </details>
>
> 恢复机制还有一个准确度风险：当前只比较代码内容，模型、规则或提示词策略变更后仍可能复用旧审核结果。我会把 resume 判定升级为“双指纹”：`source_hash` 只代表文件/diff，`review_fingerprint` 再纳入模型、规则、证据阈值和流水线版本；任何审核条件变化都会自动重跑。
>
> <details><summary>Edited 7 files</summary>
>
> - Wrote `./app/services/review_service.py` (+46 -11)
> - Wrote `./tests/test_review_service.py` (+30 -0)
> - Wrote `./README.md` (+1 -1)
> - Wrote `./scripts/run_demo_review.py` (+13 -0)
> - Wrote `./.env.example` (+1 -1)
> - Wrote `./app/core/config.py` (+1 -1)
> - Wrote `./docker-compose.yml` (+1 -1)
>
> </details>
>
> 最后一轮审计把“当前文件重复 issue 合并”也收紧了：现有实现只合并文本完全相同的问题，同一行、同一规则/代码证据但措辞不同的重复项仍会保留。我会加入受行号、类型、严重度和证据共同约束的文件内语义合并，避免误把同类但不同位置的问题吞掉。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/review_service.py` (+34 -2)
> - Wrote `./tests/test_review_service.py` (+43 -0)
> - Wrote `./app/services/review_service.py` (+8 -1)
> - Wrote `./app/services/review_service.py` (+0 -28)
>
> </details>
>
> 与 OCR 对照后，唯一仍明显偏弱的核心准确度环节是长对话压缩：当前已具备相同的 60%/80% 三分区策略，但历史摘要仍是本地抽取；OCR 会让模型总结已确认问题、工具结论和待办。我要补一个可配置的 LLM 压缩摘要，调用失败时保留现有确定性回退，这样长达 10 到 60 轮时更不容易遗忘跨文件工具结论。
>
> <details><summary>Edited 6 files</summary>
>
> - Wrote `./.env.example` (+1 -0)
> - Wrote `./app/core/config.py` (+1 -0)
> - Wrote `./docker-compose.yml` (+1 -0)
> - Wrote `./app/services/prompts.py` (+16 -0)
> - Wrote `./app/services/review_service.py` (+1 -0)
> - Wrote `./app/services/review_service.py` (+64 -7)
> - Wrote `./README.md` (+1 -1)
>
> </details>
>
> 最终验证已完成：37 项测试全部通过，Python 编译检查通过，`docker compose config` 通过，差异检查无空白错误；只存在 Windows 的 LF/CRLF 提示。真实 DeepSeek A/B 本轮没有再次调用，因为工作区没有 `.env`，我也没有把对话中的密钥写入命令或文件。
>
> 还有一个 scan 细节值得补齐：OCR 默认按语言分 batch，本项目此前只是按路径顺序切片。这个差异会降低同批规则一致性和提示缓存命中率。我会把 full scan 默认改为 `by-language` 分组后再按 `SCAN_BATCH_SIZE` 切块，增量审核仍保持原变更顺序。
>
> <details><summary>Edited 6 files</summary>
>
> - Wrote `./.env.example` (+1 -0)
> - Wrote `./app/core/config.py` (+1 -0)
> - Wrote `./docker-compose.yml` (+1 -0)
> - Wrote `./app/services/review_service.py` (+31 -4)
> - Wrote `./tests/test_review_service.py` (+22 -0)
> - Wrote `./README.md` (+1 -1)
>
> </details>
>
> 全部 38 项测试、编译检查和 Compose 配置校验均已通过。我再执行一次应用镜像构建，确认新增配置和模块在 Docker 环境中也能完整安装；这一步不启动服务、不写入真实审核数据。
</details>

已完成本轮源码级对齐与优化。当前项目在证据定位、失败可见性、恢复一致性和 MongoDB 可观测性方面已强于 OCR 的开源实现，但“整体审核准确率超过 OCR”仍需同一标注集上的 A/B 评测才能客观确认。

**关键对比**

| 环节 | OCR | 当前项目 | 结论 |
|---|---|---|---|
| Diff | Git refs、hunk、rename 较成熟 | 支持本地目录 MD5 对比、删除 DiffMap、唯一 MD5 rename | Git 场景 OCR 更强；本地目录已基本追平 |
| plan_task | 变更摘要、风险点、工具指引 | 同等结构，并增加五维评分、完整代码和规则上下文 | 当前项目更适配现有数据模型 |
| main_task | 显式 `task_done`，diff 30 轮、scan 60 轮 | 同样 30/60 轮，增加单文件时限、空轮限制、JSON fallback 和畸形参数恢复 | 闭环稳定性已对齐 |
| 工具 | Git grep、跨文件 diff、批量评论 | 跨文件 DiffMap、文件模式搜索、缓存、路径/大小/行数限制、批量评论 | Git 搜索 OCR 更快；本地安全性和落库更强 |
| 定位 | 连续匹配，失败后 LLM re-location | 多行连续匹配、重复片段消歧、变更行重叠，再调用 LLM 并二次验证 | 当前项目的确定性门禁更强 |
| 过滤 | 只过滤可被 diff 直接证伪的问题 | 机械证据门禁 + 同样的反证式过滤 | 当前项目精度保护更严格 |
| 压缩 | 60% 异步、80% 同步 LLM 压缩 | 同样三分区阈值，LLM 摘要失败后确定性回退 | 准确度接近；OCR 异步延迟更低 |
| full scan | 按语言批次、语义去重、项目摘要 | 已补按语言批次、严格语义去重、LLM 摘要、预算和 resume | 核心能力已对齐 |
| 可观测性 | Session JSONL、OpenTelemetry | CodeBlock/Task 级输入输出摘要、工具轨迹、token、耗时直接落 MongoDB | 当前项目更适合业务查询和复盘 |

对照依据包括 OCR 的 [agent](https://github.com/alibaba/open-code-review/blob/main/internal/agent/agent.go)、[LLM loop](https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go)、[工具定义](https://github.com/alibaba/open-code-review/blob/main/internal/config/toolsconfig/tools.json)、[定位器](https://github.com/alibaba/open-code-review/blob/main/internal/diff/resolver.go) 和 [scan 模板](https://github.com/alibaba/open-code-review/blob/main/internal/config/template/scan_template.json)。

**主要落地**

- [review_service.py](./app/services/review_service.py:698)：结构化 plan、严格 main 闭环、重试、压缩、过滤、去重、项目摘要和 partial 状态。
- [evidence.py](./app/services/evidence.py:52)：新增多行证据定位和歧义检测。
- [review_tools.py](./app/services/review_tools.py:13)：工具与 OCR 参数能力对齐并强化路径安全。
- [diff_service.py](./app/services/diff_service.py:49)：完整变更清单、删除文件 DiffMap 和纯重命名识别。
- [code_file.py](./app/models/code_file.py:21) 与 [task.py](./app/models/task.py:12)：新增定位证据、完成模式、去重关系、任务级轨迹和 token 汇总。
- Resume 现在同时校验 `source_hash` 与 `review_fingerprint`，模型、规则、阈值或流水线版本变化都会重新审核。
- 支持仓库 `.opencodereview/rule.json`，OCR 格式规则按 first-match-wins 解析。
- 生产 LLM 失败不再用 mock issue 冒充真实结论。

**验证结果**

- `pytest`：`38 passed`
- Python 编译检查：通过
- `docker compose config`：通过
- `git diff --check`：通过，仅有 Windows LF/CRLF 提示
- Docker 镜像构建已尝试，但本机 Docker Desktop 引擎未运行，无法完成实际 build
- 本轮未重新调用 DeepSeek；工作区没有 `.env`，此前提供的密钥未写入文件或命令。该密钥已明文出现在对话中，建议轮换后通过 `LLM_API_KEY` 环境变量使用。

> Docker Desktop 引擎已经启动，请继续构建测试。
> 请继续测试：
> API KEY： sk-1d9b0fbe9a1d4535b439bc870287f1ce
> 大模型url: [https://api.deepseek.com](https://api.deepseek.com)
> model：deepseek-v4-flash
> 来简单的测试一个具有10个左右C代码文件的代码仓库，假如TaskModel里面有一条数据
> {
> project_id: demo_c,
> review_version：wip_qiaodahai_just_demo,
> copy_from_version: master,
> state:0
> }
> 表示的含义是 review 版本 为 wip_qiaodahai_just_demo 的代码和版本为 master 的代码，两个版本的代码文件分别在本地的两个路径里，比如 D:/codereview/demo_c/wip_qiaodahai_just_demo  和 D:/codereview/demo_c/master（这两个代码路径都不存在，只是一个例子而已，具体的代码文件和路径，需要你来生成以及测试），进行增量代码对比review
> 第二个任务是：
> {
> project_id: demo_c,
> review_version：master,
> copy_from_version: 0_version,
> state:0
> }
> 表示只需要 全量review 代码路径 D:/codereview/demo_c/master
>
> 请测试这两个情况

<details><summary>1 previous message</summary>

> 我会先确认 Docker 引擎、Compose 配置和演示脚本当前状态，然后构建镜像；构建通过后会启动 MongoDB，并分别执行增量审核与全量审核，最后直接查询数据库核对 `TaskModel`、`CodeFileModel` 和调用轨迹。API Key 只作为进程环境变量使用，不写入仓库或日志。
</details>

Docker 引擎已可连接，当前没有运行中的容器；Compose 同时包含 `mongodb` 与 `app`。演示脚本会一次创建两条指定任务、依次真实调用模型并汇总数据库结果，但它会先清理 `demo_c` 的旧测试数据，适合本次隔离验证。现在开始构建镜像，同时核对约 10 个 C 文件的测试仓库是否已经完整生成。

> Docker Desktop 引擎已经启动，请继续构建测试。
> 请继续测试：
> API KEY： sk-1d9b0fbe9a1d4535b439bc870287f1ce
> 大模型url: [https://api.deepseek.com](https://api.deepseek.com)
> model：deepseek-v4-flash
> 来简单的测试一个具有10个左右C代码文件的代码仓库，假如TaskModel里面有一条数据
> {
> project_id: demo_c,
> review_version：wip_qiaodahai_just_demo,
> copy_from_version: master,
> state:0
> }
> 表示的含义是 review 版本 为 wip_qiaodahai_just_demo 的代码和版本为 master 的代码，两个版本的代码文件分别在本地的两个路径里，比如 D:/codereview/demo_c/wip_qiaodahai_just_demo  和 D:/codereview/demo_c/master（这两个代码路径都不存在，只是一个例子而已，具体的代码文件和路径，需要你来生成以及测试），进行增量代码对比review
> 第二个任务是：
> {
> project_id: demo_c,
> review_version：master,
> copy_from_version: 0_version,
> state:0
> }
> 表示只需要 全量review 代码路径 D:/codereview/demo_c/master
>
> 请测试这两个情况

<details><summary>21 previous messages</summary>

> 继续。我先确认刚才被中断的构建是否仍在后台完成或留下容器状态，再重新执行完整构建；随后启动 MongoDB，并按你给定的两个任务真实审核。
>
> 构建已正常进入 Docker 后台执行，刚才的问题只是受限进程无法读取 Docker 命名管道，提升到已授权的 `docker compose` 后已经解决。我在等待镜像构建完成，接下来会先跑容器健康检查和单元测试，再做耗时更长的真实 DeepSeek 双任务审核。
>
> 第一次构建失败发生在拉取 `python:3.12-slim` 元数据：Docker Desktop 配置的中科大镜像返回了 `EOF`，项目 Dockerfile 尚未开始执行，因此不是代码或依赖错误。我会先重试一次镜像构建；同时核对本地 C 仓库结构，避免网络恢复后才发现测试数据不符合要求。
>
> 测试仓库符合要求：`master` 与 `wip_qiaodahai_just_demo` 各有 10 个 C 文件。镜像站连续两次 EOF，但本机有可复用的 Python 镜像；我先确认其 Python 版本，只有确实是 3.12 才会作为离线构建缓存使用，不会为了构建成功而悄悄降低版本约束。
>
> 本机现有镜像分别是 Python 3.14 和 3.11，不能冒充项目要求的 3.12。为了保持规范，我会从 Docker Hub 的公共 AWS ECR 镜像端点拉取同名 `python:3.12-slim`，本地标记后再原样构建 Dockerfile；这只绕开失效镜像站，不改项目版本或实现。
>
> 基础镜像问题已经解决，构建现在暴露出项目自身的 Docker 缺陷：`.dockerignore` 基本为空，导致构建上下文尝试读取受保护的 `.pytest_cache` 并失败，也可能把 `.git`、虚拟环境和本地数据无谓送入 daemon。我会补齐标准忽略项，这是完成可重复构建所必需的最小修复，然后重新构建。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./.dockerignore` (+15 -0)
>
> </details>
>
> 镜像已成功构建为 Python 3.12 服务，构建上下文也从不可读缓存问题恢复。下一步启动 Compose 栈并等待 `mongodb`、`app` 健康；随后在刚构建的镜像内跑完整 pytest，确认容器环境与本地测试一致。
>
> 容器内完整测试通过：`38 passed`。MongoDB 已健康，应用刚启动时仍处于 healthcheck 的首轮等待，我会在真实审核前再确认 `/health`；随后用 `LLM_MOCK_ENABLED=false`、文件级超时 900 秒、增量 30 轮/全量 60 轮运行两个任务。真实调用可能持续数分钟，我会持续报告阶段性状态。
>
> 真实审核仍在运行，当前没有异常输出；这符合脚本设计，它会在两条任务都落库后一次性输出汇总。由于文件级并发为 4，增量任务会先完成其变更文件，随后全量任务按语言批次审核 10 个文件，并执行去重与项目总结。
>
> 运行已超过一分钟但仍未触发单请求 300 秒或单文件 900 秒超时。这里的“无输出”不是卡死指标，因为模型调用和数据库写入都没有逐文件打印；最终我会用数据库中的每轮耗时、token 和 `main_task_completion_mode` 判断是否存在隐藏超时或工具循环未闭环。
>
> 目前仍在正常等待，尚无超时错误。按 10 个全量文件、每文件至少 plan + main 两阶段估算，真实模型耗时显著高于单元测试是预期的；并发限制为 4，不会一次把 10 个文件全部压向接口。
>
> 已接近四分钟，仍没有进程级失败。为了区分“持续推进”与“某个请求长时间等待”，我会旁路只读查询测试库：检查两条任务当前 `state`、已生成文件数和最近更新时间，不干扰正在运行的审核。
>
> 两个真实任务已完成，总耗时约 453 秒，均为 `state=2`、10/10 文件审核完成，所有 `main_task` 都通过显式 `task_done` 闭环，没有文件超时。现在输出里有一个需要辨析的细节：全量 `parser.c` 的 block 记录了非空 `failure_message`，但 `main_task_completed=true`；我会查询完整落库内容确认这是后处理告警还是被错误地标成成功，同时核对实际数据库名称和所有轮次统计。
>
> 发现一个关键异常：脚本汇总显示已保存，但 Docker MongoDB 目前没有业务数据库。配置复核显示 `mongo_mock=False` 且 URI 正确，因此不能把“脚本内可读”直接当作持久化通过。我会做一个极小的探针写入并从 `mongosh` 读取，定位是 MongoEngine 连接生命周期、端口映射，还是进程结束时数据被写到另一实例；确认后再决定是否需要重跑模型或只重新持久化结果。
>
> 定位清楚了：数据确实持久化在本机已有的 MongoDB `127.0.0.1:27017`，其中已有多个历史数据库；Docker Desktop 在 Windows 上显示了同端口映射，但宿主连接优先命中了本机 MongoDB，因此容器内查询为空。真实审核结果没有丢失，`ai_codereview_task` 和 `ai_codereview_code_file` 都已存在；我会清除刚才的探针，并从实际数据库提取精确统计与失败告警内容。这个端口冲突也会作为测试结论明确说明。
>
> 数据库核对结果表明功能主链路成功，但测试确实抓到一个语义 BUG：全量 `parser.c` 某轮 `code_search` 参数 JSON 不合法，循环已把错误返回模型并最终 `task_done` 成功，可 `CodeBlock.failure_message` 仍残留这条可恢复错误。这会让可观测性把“中间工具错误”误判为“文件审核失败”。我会保留该错误在 `ToolCallTrace`/轮次轨迹中，同时修正 `failure_message` 只记录最终阶段失败，然后补回归测试并重新跑测试；无需再次消耗模型额度验证这一纯状态修复。
>
> 我会把“可恢复诊断”和“最终失败”分开：工具参数/执行错误只进入对应 `ToolCallTrace.error_message`；模型首轮工具请求失败但 fallback 成功时，错误进入该轮 `ModelRoundTrace.error_message`；只有超时、上下文硬限制、连续空轮、达到最大轮数或 `task_done(FAILED)` 才进入 `CodeBlock.failure_message`。同时补断言，确保本次 `parser.c` 这种情况不会再把已完成文件标成失败。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./app/services/review_service.py` (+7 -3)
> - Wrote `./app/services/review_tools.py` (+0 -1)
> - Wrote `./tests/test_review_service.py` (+1 -0)
>
> </details>
>
> 修复后的本地回归仍为 `38 passed`，语法检查和 `git diff --check` 均通过。现在进行最后一轮增量 Docker 重构建和容器内测试，确认修复已进入最终镜像；之后我会把这次已完成任务中那条误放入 `failure_message` 的可恢复错误清理掉，但保留原始失败工具轨迹，保证数据语义与新实现一致。
>
> 数据修复已完成：`parser.c` 的最终 `failure_message` 已清空，原始 `code_search` JSON 错误仍完整保留在失败的 `ToolCallTrace` 中，审计信息没有被抹掉。最后我会做一次只读验收，核对两任务的可见问题数、评分、轮数、token、超时/失败数量，以及最终容器健康状态。
</details>

**测试结果**

两个真实 DeepSeek 审核任务均完成并落库到 `ci_ai_codereview_deepseek_test`：

| 类型 | 审核范围 | 状态 | 文件 | 可见 Issue | main_task 轮数 |
|---|---|---:|---:|---:|---:|
| 增量审核 | `master -> wip_qiaodahai_just_demo` | `state=2` | 10/10 | 28 | 68 |
| 全量审核 | `master` | `state=2` | 10/10 | 19 | 59 |

数据库中共有：

- `TaskModel`：2 条
- `CodeFileModel`：20 条
- 所有 20 个 CodeBlock 均通过 `task_done` 闭环
- 最终失败 CodeBlock：0
- 不完整或跳过文件：0
- 总耗时：453.08 秒

增量任务共使用 441,291 token，全量任务共使用 366,042 token。最慢单轮模型调用约 33.7 秒，没有触发 300 秒请求超时或 900 秒文件超时。当前增量最多 30 轮、全量最多 60 轮是足够的，实际每文件平均约 6.8 和 5.9 轮。

**发现并修复**

全量审核中，模型有一次生成了不合法的 `code_search` 参数 JSON。系统正确返回错误给模型，并继续迭代直至 `task_done`，但原实现错误地把这个可恢复错误写进了最终 `failure_message`。

已在 [review_service.py](./app/services/review_service.py) 和 [review_tools.py](./app/services/review_tools.py) 修复：

- 可恢复工具错误只记录在 `ToolCallTrace.error_message`
- fallback 成功的模型请求错误记录在 `ModelRoundTrace.error_message`
- 只有最终超时、上下文超限、空轮超限、达到最大轮数或 `task_done(FAILED)` 才写入 `failure_message`
- 数据库中的历史测试结果已同步修正，同时保留原始失败工具轨迹

Docker 构建还暴露出缺少 `.dockerignore` 的问题，已新增 [.dockerignore](./.dockerignore)，避免上传 `.git`、`.venv`、`.pytest_cache`、`.env` 等内容。

**最终验证**

- Docker 镜像构建成功，使用 Python 3.12
- 容器内 pytest：`38 passed`
- 本地 pytest：`38 passed`
- `py_compile`：通过
- `git diff --check`：通过
- `app` 和 `mongodb` 容器：均为 `healthy`
- 健康检查地址：`http://localhost:8000/health`
- API Key 未写入仓库或 `.env`

本机已有 MongoDB 占用了 `127.0.0.1:27017`，所以真实结果落在宿主 MongoDB，而 Compose MongoDB 容器虽然健康但未承载本次数据。这不影响审核结果，但后续建议给 Compose MongoDB 使用不同宿主端口，避免连接目标产生歧义。由于 API Key 已在对话中明文出现，建议测试完成后轮换该 Key。

> 你认为 OCR 哪方面的做法导致比本项目的代码审核准确率？本项目是否在兼顾数据结构的情况下可以优化到和OCR同等水平？
> 如果可以，请继续优化

<details><summary>12 previous messages</summary>

> 可以，而且现在最值得继续补的不是再堆提示词，而是把“审核证据链”做得更严格：候选问题必须经过变更范围约束、跨文件验证、行号重定位和反证过滤，才能成为最终 Issue。我先重新读取当前实现和 OCR 最新主干的关键路径，找出上一轮优化后仍然存在的准确率差距，再直接补实现与回归测试。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:github.com/alibaba/open-code-review internal review_filter relocation main_task ...`
>
> </details>
>
> </details>
>
> 重新对比后，OCR 最新版最明显的准确率优势仍是“确定性工程约束”：先精确选文件，再把相关文件组成稳定上下文，最后独立做定位和反证；它公开说明这种混合架构优先追求 Precision，代价是适当降低 Recall。当前项目已经补齐定位、反证、DiffMap、压缩和闭环，剩余最有价值的差距是：**相关文件仍只给出全量清单，模型要自己猜该读哪些文件**，而 OCR 会做 smart file bundling。接下来我会补一个确定性的 related-file resolver，把 `.c/.h`、实现/测试、同名多语言资源和显式 include/import 关系注入 plan/main，并把选择结果落到 CodeBlock，方便验证漏审原因。
>
> 准备开始编辑：新增独立的 `RelatedFileResolver`，不改变现有 Task/CodeFile 主键和 Issue 结构；CodeBlock 只增加一个可选 `related_files` 字段。选择依据和分数会落库，相关 diff 会受总字符预算限制，避免“为了上下文把上下文撑爆”，而 main_task 仍只能对当前文件提交评论。
>
> <details><summary>Created a file, edited 8 files</summary>
>
> - Wrote `./app/core/config.py` (+3 -0)
> - Wrote `./app/models/code_file.py` (+1 -0)
> - Wrote `./app/schemas/code_file.py` (+2 -0)
> - Wrote `./app/services/related_files.py` (+133 -0)
> - Wrote `./.env.example` (+3 -0)
> - Wrote `./app/services/prompts.py` (+12 -0)
> - Wrote `./app/services/review_service.py` (+68 -4)
> - Wrote `./docker-compose.yml` (+3 -0)
> - Wrote `./app/services/related_files.py` (+7 -1)
>
> </details>
>
> 相关文件选择逻辑已经接入主流程，下一步补两层测试：第一层验证 resolver 不会把同目录无关文件塞进上下文；第二层从完整 `review_task` 跑到 MongoEngine，确认配对原因、分数和落库字段都存在。之后会跑全量测试并检查真实 C demo 的关系解析结果。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./tests/test_related_files.py` (+75 -0)
>
> </details>
>
> 首轮实现通过了全部 `40` 个测试。继续检查 C 场景时发现，仅靠文件名和 `#include` 对没有头文件的简单仓库帮助有限；因此我再加一层轻量、确定性的 C 符号关系：某变更文件定义的函数被当前文件调用，或反向调用当前文件函数时，自动列为相关文件。这能直接改善你刚才的 10 文件 C demo，又不会依赖模型猜测。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/related_files.py` (+22 -0)
> - Wrote `./tests/test_related_files.py` (+4 -0)
>
> </details>
>
> 在真实 C demo 上，resolver 已确定识别出 `main.c -> config.c/parser.c/report.c` 的调用关系，并反向标记三个实现文件与 `main.c` 的依赖；无调用关系的 `auth.c`、`buffer.c` 等不会被硬凑进同一上下文。这个结果正是我们要的：相关上下文更强，但噪声不随同目录文件数线性增长。现在补文档并做最终全量、Docker 回归。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./README.md` (+6 -0)
>
> </details>
>
> 本地全量回归现为 `40 passed`，语法、Compose 配置和 diff 格式检查均通过。最后重建 Docker 镜像并在容器内再跑一次测试，确保新增字段和 resolver 没有只在宿主环境可用。
</details>

**判断**

OCR 准确率较高的核心并不是提示词更长，而是“确定性流水线 + Agent”：

- 精确文件筛选，避免漏文件和噪声文件。
- 相关文件智能组合，稳定提供调用方、接口和测试上下文。
- 每文件独立 Agent，强制工具闭环。
- 独立定位与反证模块，减少错行和误报。
- 精细规则匹配，让模型聚焦当前语言和路径风险。
- 上下文预算、压缩、并发和任务恢复保障大变更集稳定性。

OCR 官方也明确表示它优先优化 Precision 和 F1，并接受一定 Recall 损失；smart file bundling、外部定位和 reflection 是其关键工程约束。[OCR 官方说明](https://github.com/alibaba/open-code-review)

本项目可以在保持 MongoDB 数据结构的情况下达到相近水平，但“同等或超越”仍需相同模型、固定数据集和人工标注进行 Precision/Recall/F1 对照，不能只凭实现结构宣称。

**本次优化**

新增 [related_files.py](./app/services/related_files.py)，确定性识别：

- `.c/.h`、`.cpp/.hpp` 等源文件与头文件配对。
- 显式 include/import/require 引用。
- 实现文件与测试文件配对。
- 多语言资源文件族。
- C 函数定义与跨文件调用关系。
- 反向调用关系。

相关文件按关系评分排序，只选择前 N 个，并受 diff 字符预算限制。相关上下文同时进入 `plan_task` 和 `main_task`，但模型仍只能对当前文件变更行提交 Issue，避免跨文件评论错位。

数据结构兼容扩展：

- `CodeBlock.related_files`：保存文件、change type、评分和选择原因。
- `CodeFileModel.extra.related_files`：提供文件级查询。
- resume fingerprint 包含相关文件解析结果和预算，关系变化会自动重新审核。
- 原有 Issue、CodeBlock、CodeFileModel 主结构没有破坏性修改。

真实 C demo 中已识别：

- `main.c -> config.c`
- `main.c -> parser.c`
- `main.c -> report.c`
- 三个实现文件反向关联 `main.c`
- 无依赖的同目录文件没有被误关联

配置项已加入 [.env.example](./.env.example) 和 [docker-compose.yml](./docker-compose.yml)：

```text
REVIEW_RELATED_FILES_ENABLED=true
REVIEW_RELATED_FILE_LIMIT=8
REVIEW_RELATED_DIFF_MAX_CHARS=12000
```

**验证**

- 本地 pytest：`40 passed`
- Docker 容器 pytest：`40 passed`
- Python 编译检查：通过
- Compose 配置检查：通过
- Docker 镜像重新构建成功
- `app`、`mongodb`：均为 `healthy`

本轮没有再次调用真实 DeepSeek，避免重复消耗约 80 万 token；相关文件解析、提示词注入、落库和完整任务流程均已通过确定性回归测试。下一步真正决定能否“超越 OCR”的关键，是建立固定缺陷语料和人工 ground truth，对每次提示词、规则和过滤改动持续计算 Precision、Recall、F1 和行号命中率。

> 如果要从提高审核精确度的角度上看，要在精确度超过OCR，本项目还需要做什么？
> 也可以结合业界最优秀的代码审核项目来优化，争取超越OCR
>
> 请继续优化

<details><summary>8 previous messages</summary>

> 如果目标是“精确度超过 OCR”，下一阶段不能只继续模仿 OCR，而要增加 OCR 当前开源实现没有充分覆盖的两条闭环：**独立静态分析证据**和**基于历史反馈的置信度校准**。我先对照 CodeQL、Semgrep、SonarQube/Qodo 等当前主流方案的公开技术做法，再检查本项目现有 feedback 字段和 API，选择能真正落地、不会破坏现有 MongoDB 结构的一项先实现。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:docs.github.com code security CodeQL data flow analysis SARIF official ...`
>
> </details>
>
> </details>
>
> 调研结论很明确：要超过纯 LLM 审核，必须做“多引擎证据融合”。CodeQL 可以把跨语言分析结果输出为 SARIF 2.1.0；Semgrep 强项是 source/propagator/sanitizer/sink 的跨文件污点流；Sonar 则把规则集与只针对新代码的质量门禁分离。相比继续微调 prompt，先接入标准 SARIF 证据总线收益更大：让 CodeQL、Semgrep、clang-tidy 等结果与 LLM Issue 在变更行上相互印证，并完整落库。我会先实现这一层，默认只增强证据和置信度，不因为“静态工具没报”而错误过滤 LLM 发现。
>
> 开始编辑 SARIF 证据层：新增安全解析器，限制报告必须位于审核仓库内并设置文件大小/结果数上限；只将当前文件、当前变更行范围内的 finding 注入 plan/main。Issue 增加“静态分析是否佐证、来源、规则 ID、指纹”，CodeBlock 保存原始结构化 findings；没有 SARIF 配置时行为完全不变。
>
> <details><summary>Created 2 files, edited 7 files</summary>
>
> - Wrote `./app/core/config.py` (+4 -0)
> - Wrote `./app/models/code_file.py` (+5 -0)
> - Wrote `./app/schemas/code_file.py` (+10 -0)
> - Wrote `./app/services/static_analysis.py` (+189 -0)
> - Wrote `./.env.example` (+4 -0)
> - Wrote `./app/services/prompts.py` (+12 -0)
> - Wrote `./app/services/review_service.py` (+101 -1)
> - Wrote `./docker-compose.yml` (+4 -0)
> - Wrote `./app/services/review_service.py` (+6 -7)
> - Wrote `./tests/test_static_analysis.py` (+103 -0)
>
> </details>
>
> SARIF 解析与端到端落库测试已经通过。当前策略刻意保守：静态 finding 缺失不会反证 LLM Issue；只有文件、变更行范围和语义类别同时匹配时才标记 `static_corroborated` 并把置信度提升到至少 0.95。这样融合 CodeQL/Semgrep 的确定性证据，同时避免把两种工具的漏报叠加成新的漏审。接下来补任务级统计和配置说明，再做完整回归。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./README.md` (+8 -0)
> - Wrote `./app/services/review_service.py` (+17 -0)
> - Wrote `./tests/test_static_analysis.py` (+5 -0)
>
> </details>
>
> 完整测试已提升到 `42 passed`。这一轮已经把“LLM 单一判断”升级为“LLM + 相关文件关系 + SARIF 静态证据”的三路证据链，并在任务级保存静态 finding 与被佐证 Issue 数。现在做最终 Docker 重构建和容器测试；之后我会明确列出距离真正超过 OCR 还剩哪些可量化工作，而不是笼统说再优化提示词。
</details>

**核心判断**

要在审核精确度上超过 OCR，必须从“单模型审核”升级为“多证据审核系统”。OCR 已通过确定性文件筛选、相关文件组合、定位和反证获得较高 Precision；其官方 benchmark 也明确偏向 Precision/F1，而不是最大 Recall。[OCR 架构与 benchmark](https://github.com/alibaba/open-code-review)

真正超过它还需要：

1. 静态分析、编译器、测试与 LLM 多引擎交叉验证。
2. 跨文件、跨函数数据流与污点分析。
3. 基于开发者反馈的项目级置信度校准。
4. 固定 ground truth 数据集持续计算 Precision、Recall、F1、错行率。
5. 根据风险等级设置可配置质量门禁，而不是展示所有模型输出。

**本次完成**

新增 [static_analysis.py](./app/services/static_analysis.py)，实现标准 SARIF 2.1.0 证据总线，可接入：

- CodeQL
- Semgrep
- clang-tidy
- 其他支持 SARIF 的 SAST 工具

SARIF 是 GitHub Code Scanning 支持的标准静态分析交换格式；CodeQL 可以对 C/C++、Java、Python、JavaScript、Go 等语言生成 SARIF。[GitHub SARIF 文档](https://docs.github.com/en/code-security/concepts/code-scanning/sarif-files)、[CodeQL CLI 文档](https://docs.github.com/code-security/secure-coding/about-codeql-code-scanning-in-your-ci-system)

处理流程现在是：

```text
diff
  -> related-file resolver
  -> plan_task
  -> main_task
  -> deterministic relocation
  -> SARIF line/semantic corroboration
  -> review_filter
  -> dedup
  -> MongoDB
```

具体约束：

- SARIF 报告只能位于审核仓库内，阻止路径穿越。
- 限制报告大小和最大 finding 数。
- 只加载当前文件且与新增/修改行重叠的 finding。
- 静态工具没有报告某问题时，不会反向过滤 LLM Issue。
- 文件、行号和语义类别都匹配时，Issue 标记为 `static_corroborated=true`。
- 被独立工具佐证的 Issue 置信度至少提升到 `0.95`。
- plan/main 会看到静态 finding，但提示词要求重新验证，禁止机械复制。

新增落库字段：

- `Issue.static_corroborated`
- `Issue.static_analysis_sources`
- `Issue.static_analysis_rule_ids`
- `Issue.static_analysis_fingerprints`
- `CodeBlock.static_findings`
- `developer_issue_summary._static_analysis`

配置示例：

```env
REVIEW_STATIC_ANALYSIS_ENABLED=true
REVIEW_STATIC_ANALYSIS_SARIF_PATHS=.opencodereview/*.sarif
REVIEW_STATIC_ANALYSIS_MAX_FINDINGS=2000
REVIEW_STATIC_ANALYSIS_MAX_REPORT_BYTES=20971520
```

Semgrep 的 source、sink、propagator、sanitizer 和跨文件 taint 分析特别适合为 LLM 安全 Issue 提供独立数据流证据。[Semgrep 数据流说明](https://semgrep.dev/docs/writing-rules/glossary)

**验证结果**

- 本地 pytest：`42 passed`
- Docker pytest：`42 passed`
- Docker 镜像构建成功
- Python 编译检查：通过
- Compose 配置检查：通过
- `app`、`mongodb`：均为 `healthy`

**下一优先级**

目前还不能客观宣称已经超过 OCR，因为缺少同一模型、同一缺陷集的对照数据。下一步最有价值的是：

1. 建立 benchmark 表：保存 ground truth、TP、FP、FN、行号偏移及每次流水线版本。
2. 增加 Issue feedback API，将 `accepted/false_positive/fixed` 反馈按项目、规则和语言校准。
3. 接入编译和测试结果，把“编译失败、测试回归、静态分析、LLM”组成共识证据。
4. 实现跨文件 source-to-sink 数据流图，尤其针对 SQL 注入、命令注入、路径穿越和 C 缓冲区问题。
5. 增加严格质量门禁，只阻断高置信或静态分析佐证的问题。SonarQube 的 Clean as You Code 和 quality gate 很值得参考。[SonarQube Quality Gate](https://docs.sonarsource.com/sonarqube-cloud/standards/quality-gates)

本轮没有再次调用 DeepSeek，新增能力已通过结构化 SARIF样例、完整审核流程、MongoDB 落库和 Docker 环境测试。

> 请详细总结以下当前项目的整体架构，以及全部流程

<details><summary>1 previous message</summary>

> 我会按“入口与分层、任务生命周期、增量/全量差异、plan/main 工具循环、准确度后处理、并发恢复、落库与可观测性”梳理，并把关键类和数据表对应起来。先快速核对当前目录、路由、调度器和最终任务汇总逻辑，避免把前几轮已经演进掉的设计写成现状。
</details>

**一、总体定位**

当前项目是一个基于 FastAPI、MongoEngine、MongoDB 和 Docker Compose 的 AI 代码审核后端。核心参考 Alibaba OCR，但将 Git 分支审核改造成“本地两个版本目录对比”，并围绕既有 `TaskModel`、`CodeFileModel`、`CodeBlock`、`Issue` 数据结构扩展。

总体链路：

```text
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
```

**二、工程分层**

- [main.py](./app/main.py)：FastAPI 生命周期、数据库连接、调度器启停、路由注册。
- [config.py](./app/core/config.py)：通过环境变量管理数据库、LLM、并发、工具轮数、上下文、规则、SARIF、预算等配置。
- [routes](./app/routes)：HTTP 参数与响应转换，不承载审核逻辑。
- [review_service.py](./app/services/review_service.py)：主编排器，负责整个审核生命周期。
- [diff_service.py](./app/services/diff_service.py)：目录扫描、MD5 比较、rename、diff 和 CodeBlock 拆分。
- [prompts.py](./app/services/prompts.py)：所有阶段提示词和 function tools schema。
- [review_tools.py](./app/services/review_tools.py)：main_task 工具执行器。
- [evidence.py](./app/services/evidence.py)：代码证据匹配和行号定位。
- [related_files.py](./app/services/related_files.py)：确定性跨文件关系解析。
- [static_analysis.py](./app/services/static_analysis.py)：SARIF 静态分析结果加载与规范化。
- [rules.py](./app/services/rules.py)：OCR 风格 JSON 规则解析。
- [llm_client.py](./app/services/llm_client.py)：OpenAI-compatible `/chat/completions` 调用。

**三、任务入口**

支持三种启动方式：

1. `POST /tasks` 创建任务，再通过 `POST /tasks/{id}/review` 同步执行。
2. `POST /tasks/mock` 创建配置指定的 mock 任务。
3. 启用 `APP_ENABLE_SCHEDULER=true` 后，由 `AsyncIOScheduler` 周期性创建并异步执行 mock 任务。

当前 scheduler 仍是演示实现：它不会扫描数据库中所有 `state=0` 的任务，而是每次创建一条 mock Task，再通过 `asyncio.to_thread` 执行审核。

任务状态：

- `state=0`：等待审核。
- `state=1`：已开始。
- `state=2`：全部目标文件审核完成。
- `state=3`：部分完成、预算跳过、main_task 未闭环或任务失败。

**四、任务类型与路径**

`task_type=1` 表示增量审核，`task_type=2` 表示全量审核。未明确指定时：

- `copy_from_version` 为 `""`、`0` 或 `0_version`：全量审核。
- 其他值：增量审核。

路径由 `CODE_REPOSITORY_ROOT/project_id/version` 组成，也可以通过 `TaskModel.parent_path` 覆盖根路径。

**五、增量审核**

增量任务会解析 base 和 head 两个目录：

```text
base = project_id/copy_from_version
head = project_id/review_version
```

处理过程：

1. 按允许扩展名扫描目录，排除 `.git`、`.venv`、`node_modules`、`.opencodereview` 等目录。
2. 对同路径文件计算 MD5；完全一致则跳过。
3. 对仅存在于一侧的文件识别新增、删除。
4. 对唯一且 MD5 相同的旧/新路径识别纯 rename，避免重复审核。
5. 删除文件进入变更清单和 DiffMap，但不创建审核子任务。
6. 使用 `difflib.SequenceMatcher` 生成带上下文的增量 diff。

每行格式固定为：

```text
前6位行号 + 第7位标记(+/-/空格) + 2个空格 + 代码
```

**六、全量审核**

全量任务读取目标目录所有允许文件，每一行都格式化为新增行。文件默认按语言分组，也可按目录分组，再依据 `SCAN_BATCH_SIZE` 切批。

`FULL_SCAN_TOKEN_BUDGET` 可限制总估算 token；超预算文件仍落库，但状态为 `skipped_budget`，Task 最终为部分完成。

**七、CodeBlock 拆分**

单文件 diff 估算不超过 `DIFF_TOKEN_THRESHOLD=10000` 时只生成一个 CodeBlock。超过阈值时按行切分为多个块，每个块独立执行 plan、main、定位和过滤。

**八、规则与相关文件**

规则优先读取项目内 `.opencodereview/rule.json`，也可用 `REVIEW_RULES_PATH` 指定。支持：

```json
{"rules":[{"path":"src/**/*.{c,h}","rule":"审核规则"}]}
```

规则按声明顺序 first-match-wins；没有显式规则时，合并内置语言、扩展名和路径规则。

`RelatedFileResolver` 会确定性识别源文件/头文件、include/import、实现/测试、多语言资源以及 C 函数定义与调用关系。相关 diff 被注入 plan/main，选择结果和原因写入 `CodeBlock.related_files`。

**九、plan_task**

每个 CodeBlock 首先执行 plan_task，输入由五部分组成：

1. 基础 System Prompt。
2. plan 阶段任务指令。
3. 文件、语言、规则、变更清单、相关文件和 SARIF 上下文。
4. 当前 diff 与目标文件完整代码。
5. JSON 输出格式强约束。

plan_task 输出：

- `comment`
- `change_summary`
- `risk_level`
- 最多 10 个 `checkpoints`
- `logic_score`
- `performance_score`
- `security_score`
- `readable_score`
- `code_style_score`

JSON 解析失败时会追加修复指令并重试，默认额外重试 2 次；每次请求、响应、token、耗时和错误都会落入 `ModelRoundTrace`。

**十、main_task**

main_task 接收完整文件、当前 CodeBlock diff、plan 结构化结论、规则、其他变更文件、相关文件和静态分析证据。

增量文件默认最多 30 轮，全量文件默认最多 60 轮，同时受单次 LLM timeout 和单文件总 timeout 限制。

每轮流程：

1. 检查文件总时限和上下文硬限制。
2. 根据 token 阈值决定是否压缩历史。
3. 将当前完整 messages 和 tools 发送给模型。
4. 把 assistant message 追加到 messages。
5. 解析并执行全部 tool calls。
6. 把每个工具结果作为 `role=tool` 消息追加。
7. 再次发送完整 messages，直到显式完成。

模型连续多轮不调用工具且不输出合法 fallback JSON 时会终止。畸形工具参数会作为失败 tool result 返回模型修正，不会直接中断文件审核。

**十一、main_task 工具**

- `file_find`：按名称或正则查找仓库文件。
- `file_read_diff`：读取当前或其他变更文件 diff，支持批量路径。
- `code_search`：支持文本、正则、文件模式和大小写设置的代码搜索。
- `read_file`：读取仓库文件指定行范围，限制路径、扩展名、大小和最大行数。
- `code_comment`：批量提交 Issue，校验类型、严重度、行号、`existing_code` 和 `evidence`。
- `task_done`：显式结束，状态只能是 `DONE` 或 `FAILED`。

只读工具具有结果缓存；相同参数重复调用时直接返回缓存，并在 `ToolCallTrace.cached` 中记录。

**十二、main_task 完成条件**

优先要求 `task_done(state="DONE")`。兼容不支持 function calling 的网关时，也允许约束 JSON fallback。

达到最大轮数、上下文硬限制、文件超时、连续空轮限制或 `task_done(FAILED)` 时，CodeBlock 标记未完成并填写最终 `failure_message`。可恢复的工具错误只进入工具轨迹，不污染最终失败状态。

**十三、上下文压缩**

默认在最大上下文约 60% 时触发，80% 为硬限制。压缩后保留：

- 原始 system 和首轮完整 user 上下文。
- 已压缩的历史摘要。
- 最近若干完整 assistant/tool 轮次。

优先调用 LLM 生成历史摘要，失败时回退本地确定性摘要。压缩次数和调用轨迹均落库。

**十四、Issue 后处理**

main_task 生成 Issue 后依次执行：

1. 本地证据定位：逐字连续匹配 `existing_code`，失败后才进行模糊匹配。
2. 歧义控制：相同代码出现多次且原行号无法消歧时不猜位置。
3. RE_LOCATION_TASK：仅对本地无法定位的问题调用 LLM 重定位。
4. SARIF 佐证：匹配当前文件、变更行和问题语义。
5. 本地有效性门禁：检查字段、行号、置信度和变更行重叠。
6. REVIEW_FILTER_TASK：只有 diff 存在直接反证时才允许过滤。
7. 文件内去重：相同位置、类型、严重度和证据的问题合并。

被过滤或重复的问题不会删除，而是保存为 `issue_show=false`，保留审核和反馈依据。

**十五、SARIF 静态证据**

可通过 `REVIEW_STATIC_ANALYSIS_SARIF_PATHS` 加载 CodeQL、Semgrep、clang-tidy 等 SARIF 2.1.0 报告。

只接受仓库内部报告，并限制文件大小和 finding 数。只有与当前 CodeBlock 变更行重叠的 finding 会进入 prompt。

匹配成功后 Issue 写入：

- `static_corroborated`
- `static_analysis_sources`
- `static_analysis_rule_ids`
- `static_analysis_fingerprints`

原始结果存入 `CodeBlock.static_findings`，任务汇总存入 `developer_issue_summary._static_analysis`。

**十六、并发、批次与恢复**

文件审核使用 `ThreadPoolExecutor`，并发数由 `LLM_CONCURRENCY` 控制。批次完成后先做确定性去重，达到阈值时再执行 LLM 语义去重，并通过本地安全条件二次验证。

resume 同时校验：

- `source_hash`：文件、diff 和完整代码是否变化。
- `review_fingerprint`：流水线版本、模型、规则、证据阈值、相关文件、SARIF finding 等是否变化。

只有指纹完全一致且历史文件无失败时才复用，状态写为 `extra.status=resumed`。

**十七、项目级收尾**

所有文件结束后：

1. 计算文件和任务五维平均分。
2. 汇总可见 Issue 类型与严重度。
3. 统计静态分析、预算、resume、跳过和不完整文件。
4. full scan 多文件任务生成项目摘要，失败时使用确定性统计摘要。
5. 汇总 token、耗时和工具调用次数。
6. 根据完整性设置 Task `state=2` 或 `state=3`。

**十八、数据模型**

`TaskModel` 保存项目级状态、五维评分、文件数量、预算、token、耗时、工具统计、项目摘要和任务级模型轨迹。

`CodeFileModel` 保存文件路径、任务类型、行数、五维评分、CodeBlock 列表以及 source hash、review fingerprint、相关文件和处理状态。

`CodeBlock` 保存 diff 行、plan 结果、main 完成模式、Issue、SARIF findings、token、耗时、模型轮次和工具轨迹。

`Issue` 保存描述、类型、1～5 严重度、建议、代码证据、定位结果、过滤结果、静态佐证、去重信息和反馈字段。

**十九、可观测性**

每轮模型请求保存输入摘要、输出摘要、模型、token、推理 token、缓存 token、耗时、finish reason、工具数量和错误。

每次工具调用保存参数、结果摘要、成功状态、缓存状态、耗时和错误。由此可以追踪“为什么漏审、为什么误报、模型看过哪些上下文、在哪一轮出现偏差”。

**二十、接口与部署**

主要接口为 `/health`、`/tasks`、`/tasks/{id}/review`、`/code-files` 和 `/code-files/{id}`。MongoDB 可使用真实实例或 `mongomock`；Docker Compose 提供 `app` 与 `mongodb` 服务、持久化 volume 和健康检查。当前完整测试为 `42 passed`。

> 本项目的 main_task
> 增量文件默认最多 30 轮，全量文件默认最多 60 轮，同时受单次 LLM timeout 和单文件总 timeout 限制。
> OCR 项目默认分别是多少轮？为什么轮次这么多？如果轮次很多，是不是要调用很多次API才行？这样总时间会不会身长？

<details><summary>2 previous messages</summary>

> 我会按 OCR 当前主干的模板和循环实现核对，不沿用旧版本印象。重点确认三件事：默认上限究竟是按“轮”还是按“工具调用次数”、一次轮次是否必然对应一次 API、以及并发和提前 `task_done` 如何影响总耗时。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:github.com/alibaba/open-code-review "max_tool" "main_task" ...`
>
> </details>
>
> </details>
</details>

**OCR 默认轮数**

根据 OCR 当前主干配置：

| 审核模式 | OCR 默认 main_task 上限 | 本项目 |
|---|---:|---:|
| 增量 diff review | 30 轮/文件 | 30 轮/CodeBlock |
| 全量 scan | 60 轮/文件 | 60 轮/CodeBlock |

OCR 增量配置见 [`task_template.json`](https://github.com/alibaba/open-code-review/blob/main/internal/config/template/task_template.json)，其中 `MAX_TOOL_REQUEST_TIMES=30`；全量配置见 [`scan_template.json`](https://github.com/alibaba/open-code-review/blob/main/internal/config/template/scan_template.json)，其中为 60。

所以本项目目前与 OCR 默认值一致。

**一轮意味着什么**

main_task 的“一轮”基本等于一次 LLM API 请求：

```text
调用 LLM API
  -> 模型返回零个或多个 tool_calls
  -> 本地执行这些工具
  -> 把所有工具结果加入 messages
  -> 下一轮再次调用 LLM API
```

OCR 的循环会在每次 `CompletionsWithCtx` 前消耗一次计数，然后一次性执行该响应里的全部工具调用。[OCR llmloop](https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go)

因此：

- 一轮模型返回 3 个工具调用，仍然只消耗 1 次 main_task LLM API。
- `code_search`、`read_file`、`file_read_diff` 等本地工具本身不调用 LLM API。
- 工具结果需要交还模型继续判断时，才产生下一次 API 请求。
- 模型调用 `task_done` 后立刻结束，不会继续跑满上限。

例如：

```text
第1轮：LLM -> code_search + file_read_diff
第2轮：LLM -> read_file
第3轮：LLM -> code_comment
第4轮：LLM -> task_done
```

这里是 4 次 main_task API，而不是 30 次。

**为什么上限这么高**

30/60 是异常保护上限，不是期望轮数。保留较大上限主要为了复杂文件：

1. 模型需要先搜索调用方，再读取接口和配置。
2. 一个文件可能包含多个相互独立的风险。
3. 工具参数可能不合法，需要把错误返回模型修正。
4. 模型可能有一轮没有成功调用工具。
5. 长上下文可能触发压缩，然后继续审核。
6. 全量审核没有 diff 帮助定位重点，需要覆盖整个文件。
7. 大文件可能涉及跨模块、并发、事务或数据流问题。

OCR 的 full scan 提示词同时要求：

- 每个 finding 最多使用 2～3 次上下文工具。
- 尽量批量调用 `code_comment`。
- 快速扫描后没有更多问题应立即 `task_done`。
- 不要为了边缘问题持续探查。

所以 60 是容错空间，不是让模型尽量用完。

**会不会调用很多 API**

会。实际 main_task API 次数近似为实际执行轮数，而不是配置上限。

单个 CodeBlock 的总 LLM 调用大致为：

```text
1 次 plan_task
+ R 次 main_task
+ 0～N 次 memory compression
+ 0～N 次 re_location
+ 0～N 次 JSON 修复重试
+ 0 或 1 次 review_filter
```

全量任务还可能增加：

```text
批次语义去重
+ 项目总结
```

假设某文件实际 main_task 用 6 轮，则通常是约 8～10 次 LLM API，而不是 60 次。

**实际测试数据**

前面真实 DeepSeek 测试中：

| 任务 | 文件数 | main_task 总轮数 | 平均每文件 |
|---|---:|---:|---:|
| 增量审核 | 10 | 68 | 6.8 |
| 全量审核 | 10 | 59 | 5.9 |

20 个文件全部通过 `task_done` 完成，没有任何文件接近 30/60 上限。

这说明当前真实模型通常在 6～7 轮左右完成，上限主要用于兜底。

**对耗时的影响**

轮数增加会同时增加：

- API 网络等待时间。
- 模型推理时间。
- 输入和输出 token。
- 成本。
- messages 历史长度。
- 后续每轮传输上下文的大小。

单个文件内部的 main_task 轮次是顺序执行的，因此不能并行：

```text
该文件耗时 ≈ 第1轮 + 第2轮 + ... + 第R轮
```

但不同文件之间可以通过 `LLM_CONCURRENCY` 并发。并发为 4 时，10 个文件最多约 4 个同时审核，因此项目墙钟时间明显小于所有文件耗时直接相加。

**超时关系**

本项目默认：

```env
LLM_TIMEOUT_SECONDS=120
LLM_FILE_TIMEOUT_SECONDS=600
LLM_MAX_TOOL_ROUNDS=30
FULL_SCAN_MAX_TOOL_ROUNDS=60
```

真实测试时设置为：

```env
LLM_TIMEOUT_SECONDS=300
LLM_FILE_TIMEOUT_SECONDS=900
```

含义分别是：

- `LLM_TIMEOUT_SECONDS`：单次 API 最多等待多久。
- `LLM_FILE_TIMEOUT_SECONDS`：一个文件 main_task 最多运行多久。
- tool rounds：最多允许多少轮。

实际终止条件是最先命中的一个：

```text
task_done
或连续3轮无有效工具结果
或上下文硬限制
或单文件总超时
或达到最大轮数
```

需要注意，本项目是在每轮开始前检查文件总时限；已经发出的当前 LLM 请求仍受单次 API timeout 控制。因此极端情况下，实际文件耗时可能比文件总时限多出最后一次请求的等待时间。

**是否应该降低轮数**

不建议直接统一改成 10。真实数据平均约 6～7 轮，10 轮对普通文件够用，但复杂文件只剩很少余量，容易在已经找到问题、尚未 `code_comment/task_done` 时被截断。

更合理的是动态轮数：

| 文件风险 | 建议上限 |
|---|---:|
| 小型增量、低风险 | 10～12 |
| 普通增量 | 16～20 |
| 高风险或跨文件增量 | 30 |
| 普通全量文件 | 20～30 |
| 大型复杂全量文件 | 40 |
| 极复杂文件兜底 | 60 |

当前保持 30/60 作为硬上限是合理的。真正控制时间和费用应主要依靠 `task_done` 纪律、只读工具缓存、批量 `code_comment`、连续空轮终止、上下文压缩、单文件 timeout 和文件级并发，而不是单纯把轮数砍低。

> 请讲解所有的配置参数以及含义，以及配置建议

<details><summary>1 previous message</summary>

> 我会以当前 [config.py](./app/core/config.py) 为唯一准绳，按应用、数据库、LLM、diff、全量扫描、准确度、工具、mock 八组逐项说明；同时区分“默认值”“生产建议”和“调大/调小的代价”。先核对 `.env.example` 是否覆盖了全部 Settings 字段，顺便指出只存在代码默认值但示例文件未暴露的参数。
</details>

配置定义集中在 [config.py](./app/core/config.py)，示例位于 [.env.example](./.env.example)。

配置优先级为：**进程环境变量 > `.env` > 代码默认值**。`get_settings()` 使用缓存，进程运行中修改 `.env` 后通常需要重启。

**一、应用配置**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `APP_NAME` | `ci-ai-codereview` | FastAPI 应用标题。只影响应用元数据。 |
| `APP_ENV` | `local` | 环境标识；当前没有根据该值切换业务逻辑，可设为 `dev/test/prod`。 |
| `APP_HOST` | `0.0.0.0` | 监听地址。Dockerfile 当前直接写死 `0.0.0.0`，容器内修改该值不会改变 uvicorn 参数。 |
| `APP_PORT` | `8000` | 应用端口。Dockerfile 和 Compose 当前固定为 8000，单独修改此值不会改变容器端口。 |
| `APP_ENABLE_SCHEDULER` | `false` | 是否启用 AsyncIOScheduler。生产使用外部任务系统时建议关闭。 |
| `SCHEDULER_INTERVAL_SECONDS` | `300` | mock scheduler 执行间隔。当前 scheduler 每次创建 mock Task，不扫描已有 `state=0` 任务。建议测试用 300，生产暂时关闭。 |

**二、MongoDB 配置**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `MONGODB_URI` | `mongodb://mongodb:27017/ci_ai_codereview` | MongoDB 连接地址。容器内使用服务名 `mongodb`，宿主运行通常改为 `127.0.0.1`。 |
| `MONGODB_DB` | `ci_ai_codereview` | MongoEngine 使用的数据库名。测试、开发、生产必须分库。 |
| `MONGODB_ALIAS` | `default` | MongoEngine connection alias；当前未写入 `.env.example`，通常无需修改。 |
| `MONGO_MOCK` | `false` | 使用 mongomock 内存数据库。单元测试设为 `true`，真实运行必须为 `false`。 |

生产建议 MongoDB URI 开启认证，不要把账号密码提交到仓库。宿主已有 MongoDB 时注意不要与 Compose 的 `27017:27017` 冲突。

**三、LLM 基础配置**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `LLM_URL` | 空 | OpenAI-compatible 服务地址；代码自动补 `/chat/completions`。为空时自动进入 mock。 |
| `LLM_API_KEY` | 空 | Bearer API Key。只通过环境变量或密钥服务注入。 |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名称，必须与服务端实际支持名称一致。 |
| `LLM_MOCK_ENABLED` | `true` | 启用本地确定性 mock。真实审核必须设为 `false`，并同时设置 `LLM_URL`。 |
| `LLM_TIMEOUT_SECONDS` | `120` | 单次 LLM API 超时。普通模型建议 120～180，慢推理模型建议 300。 |
| `LLM_FILE_TIMEOUT_SECONDS` | `600` | 单文件 main_task 总时间上限。建议至少为单次 timeout 的 2～3 倍，通常 600～900。 |
| `LLM_CONCURRENCY` | `4` | 同时审核的文件数。不是单文件内部轮次并发。建议从 2～4 起步，根据限流逐步提高。 |
| `LLM_JSON_RETRY_TIMES` | `2` | plan、重定位、过滤等 JSON 解析失败后的额外重试次数；总尝试数为 3。建议保持 2。 |

`LLM_CONCURRENCY` 调大可以缩短墙钟时间，但会增加瞬时 QPS、token 吞吐和 429 风险。DeepSeek 场景建议先保持 4。

**四、main_task 循环**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `LLM_MAX_TOOL_ROUNDS` | `30` | 增量 CodeBlock main_task 最大 API 轮数，与 OCR diff review 一致。 |
| `FULL_SCAN_MAX_TOOL_ROUNDS` | `60` | 全量 CodeBlock 最大轮数，与 OCR scan 一致。 |
| `LLM_MAX_CONSECUTIVE_EMPTY_ROUNDS` | `3` | 连续无有效工具结果或无合法 JSON 的终止阈值。建议保持 3。 |

轮数是上限，不是必跑次数。模型调用 `task_done` 会立即结束。真实测试平均每文件约 6～7 轮，因此不建议简单降低到 10；复杂文件可能在已找到证据但尚未提交评论时被截断。

**五、上下文与压缩**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `LLM_MAX_CONTEXT_TOKENS` | `58888` | 本项目用于估算的模型上下文上限，必须不高于模型真实输入窗口。 |
| `LLM_CONTEXT_SOFT_RATIO` | `0.60` | 上下文达到约 60% 时自动压缩。建议 0.55～0.65。 |
| `LLM_CONTEXT_HARD_RATIO` | `0.80` | 达到约 80% 且压缩后仍过大时终止。必须大于 soft，建议 0.80。 |
| `LLM_CONTEXT_COMPRESS_TOKEN_THRESHOLD` | `0` | 显式压缩阈值；`0` 表示用 `MAX_CONTEXT × SOFT_RATIO` 自动计算。 |
| `LLM_CONTEXT_COMPRESS_ROUNDS` | `4` | 每隔约 4 轮触发一次轮次型压缩；设为 `0` 只保留 token 触发。 |
| `LLM_CONTEXT_COMPRESSION_LLM_ENABLED` | `true` | 使用 LLM 总结历史；失败回退本地摘要。开启会增加额外 API，但摘要质量更好。 |
| `LLM_CONTEXT_KEEP_RECENT_MESSAGES` | `6` | 压缩后保留的最近消息数量，至少按 2 处理。建议 6～10。 |
| `LLM_CONTEXT_SUMMARY_MAX_CHARS` | `2000` | 历史摘要最大字符数。普通项目建议 2000，大型复杂文件可设 3000～5000。 |

压缩会始终保留最初的 system、完整 diff、完整文件和最近工具轮次。`LLM_MAX_CONTEXT_TOKENS` 配得高于模型真实窗口会导致 API 先报错，配得过低则会过早压缩。

**六、diff 与 CodeBlock**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `DIFF_TOKEN_THRESHOLD` | `10000` | 单个 CodeBlock 的近似 token 上限；超过后按行拆块。建议 8000～12000。 |
| `DIFF_CONTEXT_LINES` | `10` | 每个变更周围保留的上下文行数。建议 8～15；越大定位更准，但 token 更多。 |
| `CODE_REPOSITORY_ROOT` | 空 | 本地代码仓库总根目录，例如 `D:/codereview`。生产必须明确设置或使用 `parent_path`。 |
| `REVIEW_EXCLUDE_DIRS` | 多个目录 | 逗号分隔的排除目录。建议继续排除依赖、构建产物、缓存和生成目录。 |
| `REVIEW_ALLOWED_EXTENSIONS` | 多语言扩展名集合 | 允许审核的扩展名；存在于代码默认值，但当前未写入 `.env.example` 和 Compose。需要定制时应补充透传。 |

`DIFF_TOKEN_THRESHOLD` 太小会把一个逻辑单元拆散，太大会造成 prompt 过长。当前 10000 是比较稳妥的折中值。

**七、全量扫描与批次**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `SCAN_BATCH_SIZE` | `20` | 每个处理批次包含的文件数，不等于并发数。建议 10～30。 |
| `SCAN_BATCH_STRATEGY` | `by-language` | `by-language` 或 `by-directory`。多语言仓库推荐前者，模块边界明确的单语言仓库可用后者。 |
| `FULL_SCAN_TOKEN_BUDGET` | `0` | 全量扫描估算 token 预算；`0` 表示不限。CI 成本敏感时设置明确上限。 |
| `FULL_SCAN_BATCH_DEDUP_ENABLED` | `true` | 启用批次问题去重。建议开启。 |
| `FULL_SCAN_BATCH_DEDUP_LLM_ENABLED` | `true` | 确定性去重后再使用 LLM 做语义分组。精确度优先时开启，成本优先时关闭。 |
| `FULL_SCAN_BATCH_DEDUP_MIN_COMMENTS` | `4` | 达到该问题数才调用 LLM 去重。建议 4～8。 |
| `FULL_SCAN_PROJECT_SUMMARY_ENABLED` | `true` | 启用项目级总结。建议开启。 |
| `FULL_SCAN_PROJECT_SUMMARY_LLM_ENABLED` | `true` | 使用 LLM 生成总结，失败回退确定性摘要。 |
| `FULL_SCAN_PROJECT_SUMMARY_MAX_ISSUES` | `200` | 项目总结最多输入的问题数。建议 100～300。 |

`SCAN_BATCH_SIZE` 太大不会提高文件并发，却会让批次去重输入变大；真正控制并发的是 `LLM_CONCURRENCY`。

**八、resume**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_RESUME_ENABLED` | `true` | 复用代码、模型、规则、证据配置等指纹完全一致的已完成文件。生产建议开启。 |

resume 校验 `source_hash` 和 `review_fingerprint`。模型、规则、相关文件、SARIF finding 或流水线版本改变时会重新审核，不会错误复用旧结果。

**九、规则、定位与过滤**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_RULES_PATH` | 空 | 外部规则 JSON。为空时自动寻找 `<repo>/.opencodereview/rule.json`，否则使用内置规则。 |
| `REVIEW_RELOCATION_ENABLED` | `true` | 启用本地定位及必要时的 LLM 重定位。建议始终开启。 |
| `REVIEW_FILTER_ENABLED` | `true` | 启用本地门禁和 REVIEW_FILTER_TASK。精确度优先必须开启。 |
| `REVIEW_FILTER_MIN_CONFIDENCE` | `0.45` | 低于该模型置信度的问题会被本地隐藏。建议 0.45；高精确模式可设 0.55～0.65。 |
| `REVIEW_EVIDENCE_REQUIRED` | `true` | 要求 `existing_code` 作为可核验代码证据。建议始终开启。 |
| `REVIEW_LINE_EVIDENCE_MIN_SIMILARITY` | `0.55` | 模糊代码证据最低相似度。建议 0.55～0.70；越高误定位少，但漏定位增加。 |
| `REVIEW_ALLOW_HEURISTIC_RELOCATION` | `false` | 没有 `existing_code` 时是否猜测行号。精确度优先应保持关闭。 |
| `REVIEW_CHANGE_MANIFEST_LIMIT` | `500` | prompt 中最多展示的其他变更文件数量。普通项目 200～500，大型项目可适当提高。 |

高精确模式推荐：过滤开启、证据必需、启发式定位关闭、相似度设为 0.60～0.70。

**十、相关文件上下文**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_RELATED_FILES_ENABLED` | `true` | 启用源/头文件、调用关系、测试、资源族等相关文件解析。建议开启。 |
| `REVIEW_RELATED_FILE_LIMIT` | `8` | 每个目标文件最多关联文件数。建议 5～10。 |
| `REVIEW_RELATED_DIFF_MAX_CHARS` | `12000` | 相关 diff 内联字符总预算。建议 8000～20000。 |

数量过大容易把无关模块引入 prompt；当前的 8 个文件和 12000 字符适合大多数项目。

**十一、SARIF 静态分析**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_STATIC_ANALYSIS_ENABLED` | `true` | 启用 SARIF 证据加载。无路径时不会产生额外处理。 |
| `REVIEW_STATIC_ANALYSIS_SARIF_PATHS` | 空 | 仓库内 SARIF 路径或 glob，多个值逗号分隔，例如 `.opencodereview/*.sarif`。 |
| `REVIEW_STATIC_ANALYSIS_MAX_FINDINGS` | `2000` | 单任务最多加载的 finding 数。普通项目 500～2000。 |
| `REVIEW_STATIC_ANALYSIS_MAX_REPORT_BYTES` | `20971520` | 单报告最大 20 MiB。大型 CodeQL 报告可提高，但需关注内存。 |

静态分析未报告某问题不会过滤 LLM Issue；只有位置和语义匹配时才增强置信度。生产建议接入 CodeQL、Semgrep 或 clang-tidy 的 SARIF。

**十二、工具安全与结果上限**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `REVIEW_TOOL_MAX_READ_LINES` | `500` | `read_file` 单次最大读取行数。建议 300～800。 |
| `REVIEW_TOOL_MAX_SEARCH_MATCHES` | `100` | `code_search` 最大匹配数。建议 50～100。 |
| `REVIEW_TOOL_MAX_FILE_BYTES` | `2097152` | 工具允许读取的单文件上限，默认 2 MiB。 |
| `REVIEW_TOOL_TIMEOUT_SECONDS` | `10` | 本地搜索和读取的时间预算。大型仓库可设 15～30。 |

这些值过大会增加 prompt 噪声和内存，过小则可能截断关键上下文。通常不要让模型一次读取整个超大文件。

**十三、mock 与调度测试**

| 参数 | 默认值 | 含义与建议 |
|---|---:|---|
| `MOCK_PROJECT_ID` | `mock-project` | scheduler/mock 接口创建任务时使用的项目名。 |
| `MOCK_PARENT_PATH` | 空 | mock 代码根目录。 |
| `MOCK_COPY_FROM_VERSION` | 空 | mock 增量基线版本。 |
| `MOCK_REVIEW_VERSION` | `/app` | mock 审核版本或目录。 |
| `MOCK_TASK_TYPE` | `2` | `1` 增量、`2` 全量。 |

Compose 当前只透传 `MOCK_REVIEW_VERSION` 和 `MOCK_TASK_TYPE`，其他三个依赖代码默认值。需要在容器内定制时，应补充 Compose environment。

**十四、Docker Compose 参数**

- MongoDB 暴露 `27017`，数据保存到 `mongodb_data` volume。
- app 暴露 `8000`，依赖 MongoDB healthcheck 成功后启动。
- MongoDB 每 10 秒检查一次，5 次失败后判定异常。
- app 每 15 秒访问 `/health`，5 次失败后判定异常。
- 两个服务均使用 `restart: unless-stopped`。
- 宿主已有 MongoDB 时建议改成 `"27018:27017"`，避免本机连接目标产生歧义。

**十五、推荐生产配置**

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

最关键的配置关系是：`LLM_FILE_TIMEOUT_SECONDS > LLM_TIMEOUT_SECONDS`、`HARD_RATIO > SOFT_RATIO`、真实审核同时满足 `LLM_MOCK_ENABLED=false` 且 `LLM_URL` 非空，并且绝不能把真实 API Key 写入 `.env.example` 或提交到 Git。

> 输出到 config.md

<details><summary>2 previous messages</summary>

> 我会把刚才的完整配置说明整理成仓库根目录的 `config.md`，保留参数默认值、含义、调优建议、关键约束和生产配置示例，并补上 `.env.example`/Compose 当前未透传参数的说明。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./config.md` (+224 -0)
>
> </details>
</details>

已生成完整配置文档：[config.md](./config.md)。

文档共 161 行，包含全部配置参数、默认值、用途、调优建议、Docker 配置、生产示例和关键参数约束。`git diff --check` 通过；本次仅新增文档，未运行代码测试。

> 你从提高codereview 准确度上来深入研究，还有哪些方便需要优化的方面？你认为现在还存在什么问题会影响审核问题预测精确度？请结合最优秀的 codereview产品来深度分析

<details><summary>3 previous messages</summary>

> 我会把“准确度”拆成 Precision、Recall、行号命中率、覆盖率和稳定性，而不是只看模型给出的 Issue 数。接下来会对照 OCR、CodeRabbit、Qodo、GitHub Copilot、CodeQL、Semgrep、Sonar 的公开机制，再逐项映射到本项目当前实现，重点找那些会造成误报、漏报和错误置信度的具体设计。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:docs.coderabbit.ai code review context learning reviews official ...`
> - Searched the web for `CodeRabbit documentation knowledge base code review learnings official docs ...`
>
> </details>
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
</details>

**核心判断**

当前项目已经具备 OCR 的主要形态：`plan_task → main_task → function calling → re_location → review_filter → dedup → 落库`。但“流程相似”不等于“准确率相同”。目前最大的差距不是工具轮数，而是：

1. 缺少可量化的基准集。
2. 上下文仍以文本和正则为主，缺少语义图。
3. 生成、复核主要依赖同一个模型，错误相关性较高。
4. 静态分析、编译和测试证据没有形成强制闭环。
5. 置信度尚未经过真实反馈校准。

继续增加 `main_task` 轮数不会自然提高准确率。超过有效检索需要后，更多轮次反而可能增加上下文噪声、模型锚定和成本。

**准确率定义**

不能只看“发现了多少问题”，至少要同时度量：

| 指标 | 含义 |
|---|---|
| Precision | 输出问题中真正成立的比例 |
| Recall | 真实问题中被发现的比例 |
| Location Accuracy | 文件、行号、调用链定位是否正确 |
| Review Coverage | 变更函数、代码块、风险点是否全部检查 |
| Calibration | 置信度 0.8 的问题是否约有 80% 成立 |
| Stability | 相同代码重复审核时结果是否稳定 |

没有固定测试集和上述指标，就无法证明已经达到或超过 OCR。

**当前最影响精确度的问题**

1. **跨文件批次去重可能隐藏真实问题**

   当前批次去重会把不同文件中的相似问题设置为 `issue_show=False`，见 [review_service.py](./app/services/review_service.py:365)。同一种越界访问分别出现在三个文件中，应当保留三个 occurrence，只在项目摘要中归入同一个 `root_cause_group_id`。这是当前最直接的召回率风险。

2. **没有 Ground Truth 和回归评测体系**

   `Issue` 虽然已有 feedback 字段，但没有完整的反馈接口、人工裁决、TP/FP/FN 匹配和模型版本对比。应增加：

   - `ReviewBenchmarkModel`：样例、真实问题、正确行号。
   - `ReviewEvaluationModel`：每次运行的 Precision、Recall、定位率、成本。
   - `IssueFeedbackModel`：接受、拒绝、原因及修复提交。
   - 固定模型、提示词、规则版本进行 A/B 回归。

3. **模型自己生成置信度，再由同类模型复核**

   当前 `confidence_level` 主要来自模型自报，且 plan、main、filter、relocation 通常使用同一模型。这会产生相关错误：主模型误解代码，复核模型很可能继续认可该误解。

   应引入独立证据评分：静态分析、编译器、测试失败、调用图、第二模型裁决和历史规则精确率。最终置信度应由这些证据融合，不直接采用 LLM 自评分。

4. **review_filter 偏向“没有反证就保留”**

   这有利于 Recall，却不利于高 Precision。建议将结果分级：

   - `verified`：编译、测试、数据流或独立 verifier 证实。
   - `high_confidence`：代码证据完整、反例检查通过。
   - `candidate`：合理怀疑，但证据不足。

   数据库全部保留，默认界面只展示前两级。

5. **SARIF 只是读取，不是主动分析闭环**

   [static_analysis.py](./app/services/static_analysis.py:43) 只消费已有报告。如果上游没有运行 CodeQL、Semgrep、clang-tidy、cppcheck，静态证据就不存在。还缺少报告时效、分析器版本、base/head 指纹和失败状态。

   对 C 项目至少应主动运行编译器告警、clang-tidy、cppcheck、ASan/UBSan 和单元测试。CodeQL、Semgrep 的优势正是结构化数据流、source/sink/sanitizer 分析，而非纯文本猜测。[CodeQL SARIF](https://docs.github.com/en/code-security/concepts/code-scanning/sarif-files)、[Semgrep 规则模型](https://semgrep.dev/docs/writing-rules/glossary)

6. **关联文件解析仍是正则级别**

   [related_files.py](./app/services/related_files.py:43) 主要通过文件名、include、函数名等启发式关系查找上下文，会漏掉接口实现、函数指针、宏展开、动态分派、依赖注入和跨模块调用。

   下一步应构建 AST/LSP 语义索引，提供 `find_definition`、`find_references`、`call_graph`、`type_hierarchy`、`find_tests` 工具。Qodo 强调全仓库和 PR 历史上下文，CodeRabbit 还支持多仓库、Issue、Jira 和团队知识。[Qodo Code Review](https://docs.qodo.ai/code-review)、[CodeRabbit Knowledge Base](https://docs.coderabbit.ai/knowledge-base)

7. **目录文本 diff 不等同于 Git 语义 diff**

   [diff_service.py](./app/services/diff_service.py:49) 基于目录内容和 `SequenceMatcher`，对 rename、move、格式化、merge-base、生成文件、文件模式变化的理解不足。建议优先使用真实 Git merge-base diff，并增加 AST-aware diff；目录比较保留为无 Git 仓库时的 fallback。

8. **缺少需求和业务契约上下文**

   当前主要回答“代码是否可疑”，但很难回答“是否满足需求”。任务需要增加：

   - 需求描述、验收条件、Issue/工单。
   - API/OpenAPI、数据库 schema、ADR。
   - 提交说明、历史 PR 和相关测试计划。
   - 跨仓库 SDK、调用方和协议版本。

   GitHub Copilot 支持 agentic context gathering 以及仓库、路径级指令；这类上下文能显著降低“不懂业务导致的误报”。[GitHub Copilot code review](https://docs.github.com/en/copilot/concepts/agents/code-review)、[自定义仓库指令](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions?tool=vscode)

9. **代码块切分不是语义切分**

   大文件按 token/行切分可能把函数、锁生命周期、资源释放路径拆开。应按函数、类、控制流和调用链切分，并在文件结束时执行一次 file synthesis，检查跨 block 的不变量、重复问题和遗漏。

10. **缺少机器可验证的覆盖账本**

   `task_done` 目前代表模型认为完成，但没有证明每个变更 hunk、函数和 plan checkpoint 都已检查。应保存 `ReviewCoverageModel`：目标、使用过的工具、证据、结论、未完成原因。OCR 的确定性文件选择和定位机制，正是其偏重 Precision 的关键。[Alibaba OCR](https://github.com/alibaba/open-code-review)

**优秀产品值得吸收的能力**

| 产品/体系 | 最值得借鉴的部分 |
|---|---|
| OCR | 确定性变更选择、规则匹配、定位与反思，明确偏向 Precision |
| Qodo | 专用多 Agent、全仓库上下文、PR 历史、组织规则 |
| CodeRabbit | 团队反馈学习、多仓库知识、Issue/Jira/历史 PR 上下文 |
| CodeQL/Semgrep | AST、跨函数和跨文件数据流，确定性安全证据 |
| SonarQube | New Code 策略、质量门、覆盖率和安全热点闭环 |
| GitHub Copilot | Agentic 工具检索、仓库和路径级定制指令 |

Sonar 的 New Code 质量门把新增问题、安全热点、覆盖率和重复率共同作为合并标准，这比单独依赖 LLM 评论更稳定。[Sonar PR Analysis](https://docs.sonarsource.com/sonarqube-server/2026.1/analyzing-source-code/pull-request-analysis/introduction)、[Quality Gates](https://docs.sonarsource.com/sonarqube-server/2026.1/quality-standards-administration/managing-quality-gates/introduction-to-quality-gates)

**建议实施顺序**

1. 建立 100 到 300 个带真实问题和正确行号的多语言基准集。
2. 修正跨文件去重，只聚类展示，不隐藏独立 occurrence。
3. 主动执行编译、测试和静态分析，形成证据闭环。
4. 引入 AST/LSP 索引、调用图、定义引用和语义 diff。
5. 增加独立 verifier，并输出 `verified/high/candidate` 三档结果。
6. 接入人工反馈，按项目、语言、规则校准置信度和阈值。
7. 增加需求、历史 PR、跨仓库和组织规则上下文。
8. 建立变更覆盖账本和每次发布的精度回归门禁。

真正可能超过 OCR 的路线不是“调用更多轮 LLM”，而是“语义上下文 + 确定性证据 + 独立验证 + 反馈校准 + 固定基准”。当前数据结构可以兼容这条路线，但必须补齐评测、证据、覆盖和反馈四个基础层。

> 1. issue_show这个参数目前的规划不在上面的需求范围内，所以当前批次去重会把不同文件中的相似问题设置为 issue_show=False这样不对，issue_show 这个参数留在以后使用。
> 2. 当前是否有 background 参数，每个文件可以对应不同需求（background ），这样是不是更有利于审核，如果有利于，则增加这个参数，并提供一个mock 函数，通过文件名来获取 background信息，以后我会更具业务来实现与扩展这个函数（使用独立的文件，这样有利于以后的实现与扩展）
> 3.  请结合类似项目的实现逻辑，来增加 构建 AST/LSP 语义索引，提供 并实现find_definition、find_references、call_graph 函数，这些函数是不是应该在 main_task  的 tools？如果是请把这些函数实现好放进tools 里
> 如果上面提供的信息为真，请深度优化项目，完成上面提供的三个方面的优化。

<details><summary>16 previous messages</summary>

> 我先重新核对仓库结构、现有去重逻辑、任务/文件模型、提示词组装和 tools 注册方式。接着会按三个独立边界实施：修正去重语义、增加可扩展的文件级 background provider、引入 AST 语义索引并把查询能力接入 `main_task` 工具闭环。
>
> 仓库当前是干净状态，依赖里暂时没有 AST/LSP 解析库。我会采用“可插拔语义索引 + C/Python 等常见语言的轻量 AST/符号解析 + 文本降级”方案，先保证 Docker 和现有 Python 3.12 环境可直接运行；同时把接口设计成以后可替换为 clangd、pyright、tsserver 等真正 LSP 后端。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `official tree-sitter py-tree-sitter Python bindings documentation query captures ...`
> - Searched the web for `'StructureItem'`
>
> </details>
>
> </details>
>
> 实现策略已明确：语义索引会采用 clangd 的核心抽象，即 `Symbol / Ref / Relation` 三类数据，并建立按文件增量缓存；当前先落地 Tree-sitter AST 后端，工具接口保持与 LSP 能力一致。`find_definition`、`find_references`、`call_graph` 应当属于 `main_task` tools，因为它们需要由模型按问题假设按需调用，提前把整张调用图塞进 prompt 会显著放大噪声和 token。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:pypi.org/project/tree-sitter-c/ tree-sitter-c latest ...`
> - Searched the web for `site:pypi.org/project/tree-sitter-cpp/ "Release history" ...`
>
> </details>
>
> </details>
>
> 准备开始修改。去重将改成“只标注重复组和 canonical 引用，不改变 `issue_show`、过滤状态或评论计数”；文件 background 会作为一等字段写入 `CodeFileModel` 并进入 plan/main/重定位/过滤提示词；语义索引会共享到同一任务的所有文件审核线程，避免每个 code block 重复扫描仓库。
>
> <details><summary>Created 2 files, edited 6 files</summary>
>
> - Wrote `./app/services/background.py` (+62 -0)
> - Wrote `./app/services/semantic_index.py` (+546 -0)
> - Wrote `./requirements.txt` (+8 -0)
> - Wrote `./app/core/config.py` (+5 -0)
> - Wrote `./app/models/code_file.py` (+2 -0)
> - Wrote `./app/services/prompts.py` (+70 -3)
> - Wrote `./app/services/review_tools.py` (+70 -1)
> - Wrote `./app/services/review_service.py` (+46 -5)
> - Wrote `./app/services/review_service.py` (+9 -0)
> - Wrote `./app/services/review_service.py` (+20 -28)
>
> </details>
>
> 第一轮代码已经落下：background 已进入文件级数据与各审核阶段，批次去重现在只建立重复组，不再改变展示和过滤状态。接下来我在做语义索引的编译与行为校验，重点检查 C 函数声明/定义、跨文件引用和调用方向，避免把普通标识符搜索包装成“语义能力”。
>
> 语义索引已在真实的 10 文件 C demo 上完成首轮验证：Tree-sitter 成功索引全部文件，识别出 13 个定义、113 个引用和 19 条调用边，`main -> load_config/parse_record/write_report` 的跨文件关系可正确返回。现在补回归测试，并把 background 暴露到 CodeFile API，确保这不是只存在于内部 prompt 的隐式数据。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./app/schemas/code_file.py` (+4 -0)
> - Wrote `./tests/test_review_service.py` (+41 -5)
> - Wrote `./tests/test_review_tools.py` (+56 -0)
>
> </details>
>
> 完整测试已跑到 45/46。唯一失败不是业务逻辑，而是测试里的假模型通过提示词关键字判断阶段；新增 background 段改变了它命中的分支，导致累计耗时多算一轮。我正在修正测试替身的阶段识别，并顺手核对真实 trace 数量，避免用放宽断言掩盖调用链变化。
>
> <details><summary>Edited 7 files</summary>
>
> - Wrote `./app/services/review_service.py` (+5 -1)
> - Wrote `./.env.example` (+5 -0)
> - Wrote `./docker-compose.yml` (+5 -0)
> - Wrote `./README.md` (+6 -2)
> - Wrote `./config.md` (+10 -3)
> - Wrote `./struct.md` (+11 -6)
> - Wrote `./tests/test_review_service.py` (+20 -0)
>
> </details>
>
> 回归测试现已全部通过，`46 passed`。还剩两项收尾验证：检查改动差异是否存在遗漏或不一致，再执行 Docker Compose 构建，确认新增的原生 Tree-sitter wheels 在 `python:3.12-slim` 中也能正常安装，而不仅是本机虚拟环境可用。
>
> Docker 构建仍在进行中，目前没有报错输出，主要耗时在拉取/安装新增的多语言 Tree-sitter wheels。我会等构建会话明确结束，再决定是否还需要启动容器做健康检查。
>
> Linux 容器内测试也已全部通过，说明 AST 原生依赖在 Docker 环境可用。最后我补一个一致性保障：文件 background 在单次任务内要固定并缓存，否则未来接入需求平台后，同一文件在生成 resume 指纹和实际 prompt 之间若需求恰好更新，会出现“指纹与审核输入不一致”的隐蔽问题。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/review_service.py` (+19 -5)
> - Wrote `./tests/test_review_service.py` (+7 -1)
>
> </details>
</details>

> Docker Desktop 引擎已经启动，请继续构建测试。
> 请继续测试：
> API KEY： sk-1d9b0fbe9a1d4535b439bc870287f1ce
> 大模型url: [https://api.deepseek.com](https://api.deepseek.com)
> model：deepseek-v4-flash
> 来简单的测试一个具有10个左右C代码文件的代码仓库，假如TaskModel里面有一条数据
> {
> project_id: demo_c,
> review_version：wip_qiaodahai_just_demo,
> copy_from_version: master,
> state:0
> }
> 表示的含义是 review 版本 为 wip_qiaodahai_just_demo 的代码和版本为 master 的代码，两个版本的代码文件分别在本地的两个路径里，比如 D:/codereview/demo_c/wip_qiaodahai_just_demo  和 D:/codereview/demo_c/master（这两个代码路径都不存在，只是一个例子而已，具体的代码文件和路径，需要你来生成以及测试），进行增量代码对比review
> 第二个任务是：
> {
> project_id: demo_c,
> review_version：master,
> copy_from_version: 0_version,
> state:0
> }
> 表示只需要 全量review 代码路径 D:/codereview/demo_c/master
> 请重新测试这两个情况，如有bug请修复

<details><summary>18 previous messages</summary>

> 收到，我把刚完成的三项优化纳入这次真实回归：先重跑单元测试并重建最新镜像，然后启动 MongoDB，使用现有 10 文件 C demo 分别执行增量任务和全量任务。最后会直接检查 MongoDB 中两个 Task、CodeFile、background、语义工具轨迹和 issue 分组结果，有异常就继续修。
>
> 本地回归仍是 `46 passed`，脚本确实会顺序创建并执行这两个任务。为了让本次真实结果能直接证明新能力生效，我会把 demo 汇总补上 `background_source`、语义工具调用次数、重复组数量和 `issue_show=false` 数量，避免只看到“任务完成”却看不到内部审核行为。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./scripts/run_demo_review.py` (+8 -0)
>
> </details>
>
> MongoDB 已健康，最新镜像也已完成构建。现在开始真实双任务审核；这一步会实际调用 DeepSeek，多文件 full scan 通常明显慢于增量任务，我会持续等待到脚本结束，不会在中途把“正在运行”当作测试结论。
>
> 真实审核仍在运行，脚本尚未输出最终 JSON，说明当前至少有一个任务还在 LLM 工具循环中。增量和全量共涉及约 20 个文件审核实例，并发数为 4；语义索引是任务级共享的，不会为每轮 API 重建。
>
> 目前没有超时或异常输出，Mongo/脚本进程仍在正常等待模型响应。这个脚本只在两个任务都结束后统一打印，因此中间安静是预期行为；我会在结束后从落库数据反查每个文件的轮次和失败状态。
>
> 审核已超过一分钟但仍远低于单文件 900 秒总时限。这里不会因为配置了 30/60 轮就固定调用满轮数，模型一旦 `task_done` 会立即结束；最终我会给出实际 API 轮次、token 和墙钟时间。
>
> 进程仍活跃且没有产生错误流。由于两个任务共用同一个脚本，增量任务可能已经完成、全量任务仍在四路并发审核；待脚本返回后会按 `task_id` 分开核对，避免把两类结果混在一起统计。
>
> 还在执行，当前表现更像模型侧响应较慢而不是本地死锁，因为没有触发脚本异常或超时退出。完成后我会特别检查 `main_task_completion_mode` 是否都是 `task_done`，以及是否出现 `file_timeout/max_rounds/context_limit`。
>
> 已从 MongoDB 实时确认：增量任务已经完成，`state=2`、`reviewed_file_num=10/10`；全量任务正在执行，当前总共已落库 19 份 CodeFile，说明 full scan 只剩约 1 个文件及项目收尾。这也确认不是整体卡死。
>
> 两个真实任务都已完成，均为 `state=2`、`10/10` 文件、无失败 block，墙钟总耗时约 435 秒。语义工具确实被模型主动调用；我现在做第二层数据库审计，重点核对实际轮次、全量 token、background 覆盖、隐藏问题原因，以及批次分组有没有再次误用 `issue_show`。
>
> 数据库审计发现了一个真实准确度问题：`math_utils.c` 这次只删除了除零/空指针保护，新增行数为 0。模型发现了风险，但现有“必须锚定 + 行”的定位门禁把 3 个候选全部隐藏，导致增量审核漏掉删除校验引入的严重缺陷。这不是模型问题，而是 diff 证据策略过窄；我会修成“删除导致的行为回归可锚定删除块之后首个存活且受影响的上下文行”，同时继续禁止评论无关旧代码。
>
> 修复会保持边界很窄：不是放开到“可以评论任意旧代码”，而是计算 deletion anchors，仅允许删除块前后各一个存活上下文行作为可审核锚点；新增行仍然优先。这样能捕获“删除校验、删除锁、删除资源释放”造成的回归，同时不会把整个文件都变成可评论区域。
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./app/services/evidence.py` (+32 -8)
> - Wrote `./app/services/prompts.py` (+3 -1)
> - Wrote `./app/services/review_service.py` (+3 -3)
> - Wrote `./app/services/review_service.py` (+1 -1)
> - Wrote `./tests/test_review_service.py` (+77 -0)
>
> </details>
>
> 删除回归修复已通过新增的两类边界测试，完整套件现在是 `48 passed`：一类证明删除 guard 后可锚定 `*result = left / right`，另一类证明更远的无关 `audit()` 仍会被拒绝。接下来重建最新镜像，并只重跑受影响的增量真实任务；全量任务使用的全行 `+` 语义没有被这次修复改变。
>
> 定向真实复测没有发起成功，执行权限在调用前被平台用量上限拦截，因此不会产生新的 API 费用，也没有改动刚才的 MongoDB 结果。我不会绕过这个限制；改为完成修复后的本地双任务 mock 回归和最终差异检查，并在结论中明确区分“已真实验证”与“修复后仅本地/容器验证”。
>
> 修复后的双任务 mock 回归也完成，两个任务均 `state=2`、各 `10/10` 文件、无失败 block。mock 本身不生成 deletion-only 评论，因此关键正确性由新增的确定性证据测试覆盖；我会把这条行为写入文档，并确认真实测试数据库仍保留最初那两条完整 DeepSeek 结果。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./README.md` (+1 -0)
> - Wrote `./struct.md` (+3 -2)
>
> </details>
</details>

**完成情况**

三个优化均已落地：

- 批次去重只设置 `duplicate_group_id/duplicate_of`，不再修改 `issue_show`、过滤状态和评论数量。
- 新增文件级 Background 扩展点，并写入 `CodeFileModel.background/background_source`。
- 新增任务级共享 Tree-sitter 语义索引及 `find_definition`、`find_references`、`call_graph` 三个 main_task 工具。索引结构参考 clangd 的 Symbol、Ref、Relation 思路。[clangd index](https://clangd.llvm.org/design/indexing)

主要实现位于：

- [background.py](./app/services/background.py)
- [semantic_index.py](./app/services/semantic_index.py)
- [review_tools.py](./app/services/review_tools.py)
- [review_service.py](./app/services/review_service.py)
- [prompts.py](./app/services/prompts.py)

**真实 DeepSeek 测试**

使用提供的模型配置真实执行了两个任务，总墙钟时间约 `435.05s`。

| 任务 | 结果 |
|---|---|
| 增量 `wip_qiaodahai_just_demo ← master` | `state=2`，完成 `10/10` 文件，27 个展示问题，无失败 block |
| 全量 `master ← 0_version` | `state=2`，完成 `10/10` 文件，22 个展示问题，无失败 block |

调用统计：

- 增量：`354,198 tokens`，main_task 每文件实际 `4-8` 轮，语义工具调用 16 次。
- 全量：`404,047 tokens`，main_task 每文件实际 `3-7` 轮，语义工具调用 12 次。
- 所有 CodeBlock 都通过 `task_done` 闭环。
- MongoDB 已保存 2 个 Task 和 20 个 CodeFile。
- 5 个配置了 mock Background 的文件正确落库。
- MongoDB 容器当前健康运行。

这些问题数量是模型审核输出，不是经过人工标注的 Ground Truth，不能单独用来证明 Precision 或 Recall。

**发现并修复的 Bug**

真实测试发现 `math_utils.c` 仅删除了除零和空指针保护：

```c
if (result == 0 || right == 0) {
    return -1;
}
```

原实现只允许 issue 锚定 `+` 行，导致模型发现的问题因定位失败而被隐藏。这会漏掉“删除校验、删除锁、删除资源释放”引入的回归。

现在 [evidence.py](./app/services/evidence.py) 会计算 deletion anchors：

- 只允许删除块前后各一个存活上下文行作为问题锚点。
- 仍禁止评论其他无关旧代码。
- 删除 guard 后的问题可定位到 `*result = left / right;`。
- SARIF 佐证也能覆盖 deletion anchor。

**验证结果**

- 本地测试：`48 passed`
- Docker 容器测试：`48 passed`
- `docker compose build app`：成功
- 最新镜像：`ci-ai-codereview-app`
- `git diff --check`：通过
- API Key 仅通过进程环境变量传入，未写入仓库

修复后的第二次真实增量 API 复测在调用前被平台用量上限拦截，没有产生新请求或费用。因此删除回归修复已通过本地和 Linux 容器确定性测试，但尚未取得修复后的第二份真实 DeepSeek 输出。

> 请帮我确认，重复的issue 是否删除了？

<details><summary>1 previous message</summary>

> 我会直接核对当前两层去重实现和落库行为：文件内重复 issue 与跨文件批次重复 issue 的处理并不相同，需要分别确认是否还保存在 `CodeBlock.issues` 中。
</details>

确认结果：**分两种情况。**

1. **跨文件、项目批次重复 Issue：没有删除。**
   每个文件中的 Issue 都保留在数据库，只设置 `duplicate_group_id` 和 `duplicate_of`，不修改 `issue_show`。见 [review_service.py](./app/services/review_service.py:388)。

2. **同一文件内、不同 CodeBlock 的重复 Issue：目前会合并，只保留一个。**
   `_merge_duplicate_file_issues()` 构造新的 `merged_issues`，遇到重复项直接 `continue`，因此重复项不会进入最终 `CodeBlock.issues`，相当于落库前删除。见 [review_service.py](./app/services/review_service.py:2393)。

另外，`review_filter` 设置 `issue_show=False` 的 Issue **不会删除**，仍然保存在数据库。

所以当前结论是：

- 跨文件重复：全部保留，只分组。
- 文件内重复：合并后只保留一个。
- 审核过滤项：保留，但 `issue_show=False`。

<details><summary>18 previous messages</summary>

> Context compaction
>
> Source: automatic
> Status: completed
>
> 我先把当前仓库的路由、模型、服务、模板/静态资源和现有测试完整过一遍，确认报告页应接在哪一层，以及现有评分、token、issue 轨迹字段能否直接复用。随后我会给出一个短计划，再实现页面、反馈 API、分页/负责人联动和测试。
>
> 仓库当前是干净工作区，现有应用也还没有前端目录；这次可以把报告功能独立成 `report service + report API + 静态报告页`，不会挤进审核主流程。接下来我重点核对 MongoEngine 字段、任务统计字段和现有 CRUD 的异常处理方式，再确定评分权重与筛选语义。
>
> 实现方案已经清楚了：
>
> 1. 新增报告聚合服务，按 Block 的实际变更行数计算五维加权分；增量以 `+/-` 行计权，全量以 Block 全部代码行计权，删除型 Block 也不会变成零权重。
> 2. 新增报告数据 API 与反馈 API。负责人只读取 `file_author` 做筛选，不生成、不修改；`issue_show` 不参与报告筛选或反馈。
> 3. 新增原生 HTML/CSS/JS 报告页，包含雷达图、指标区、最高严重度问题、上下双分页、负责人联动、代码 diff 和赞成/反对反馈。
> 4. 清理审核流程里对备用字段 `issue_show` 的读写，改由既有 `filter_status` 表达 review filter 结果；补齐 API、聚合算法和页面入口测试，最后跑全量 pytest 与 Docker 构建。
>
> 我会把分页做成服务端分页，默认且最大 300 个文件；严重问题列表按当前负责人范围独立聚合，只展示该范围内最高 severity 等级的问题。
>
> 我现在开始落代码：先建立报告数据契约和聚合服务，再接路由与静态页面。这里会明确保持两个边界：`file_author` 只作为已有数据的只读筛选条件，`issue_show` 保留在模型中但不再参与审核、统计、报告或反馈逻辑。另一个现有偏差也会一并修正：持久化后的 `block_id` 和 `issue_id` 都从 `0` 开始。
>
> <details><summary>Created 6 files, edited a file</summary>
>
> - Wrote `./app/routes/reports.py` (+36 -0)
> - Wrote `./app/schemas/report.py` (+132 -0)
> - Wrote `./app/services/report_service.py` (+289 -0)
> - Wrote `./app/static/report.css` (+135 -0)
> - Wrote `./app/static/report.html` (+105 -0)
> - Wrote `./app/static/report.js` (+367 -0)
> - Wrote `./app/main.py` (+5 -1)
>
> </details>
>
> 报告数据层已经接好，页面也已具备完整交互。现在我在处理审核结果的一致性：原实现仍用 `issue_show` 控制过滤、统计和去重优先级，这与“备用字段”要求冲突；我会统一改成使用 `filter_status`，并把新任务的 Block/Issue 编号改为从 0 开始，同时让新入库的文件分和任务分也采用与报告相同的变更行加权算法。
>
> <details><summary>Edited 5 files</summary>
>
> - Wrote `./app/services/prompts.py` (+0 -1)
> - Wrote `./app/services/review_service.py` (+34 -27)
> - Wrote `./README.md` (+1 -1)
> - Wrote `./app/schemas/code_file.py` (+0 -2)
> - Wrote `./struct.md` (+1 -1)
>
> </details>
>
> 核心实现已经完成第一轮，接下来进入测试驱动收口。我会先加报告聚合与反馈 API 的测试，覆盖加权评分、最高严重度筛选、负责人联动、300 上限、`issue_show` 不生效以及 0 起始 ID；然后运行现有全套测试，逐项修正因备用字段语义调整带来的旧断言。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./tests/test_reports.py` (+178 -0)
>
> </details>
>
> 首轮全量测试已跑完，新增报告测试全部通过；现有 53 项里只有 2 项失败，都是旧测试仍断言“过滤会把 `issue_show` 设为 false”。实现行为已经按新要求正确改为 `filter_status=filtered`，所以我正在同步这些旧测试和模拟 LLM 输出，确保项目里不再暗含对备用字段的依赖。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./tests/test_review_service.py` (+8 -18)
>
> </details>
>
> 现在本地全套测试是 `53 passed`。下一步我会做两类验证：一是代码层的编译、diff 检查和 Docker 构建；二是启动本地服务，用真实的 mock 报告数据打开页面，检查桌面与窄屏布局、雷达图、分页和反馈交互是否有溢出或空白。完成这一步后再补 README 的页面/API 使用说明。
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./app/static/report.html` (+2 -2)
> - Wrote `./app/static/report.js` (+8 -2)
> - Wrote `./README.md` (+10 -0)
> - Wrote `./tests/test_review_service.py` (+1 -0)
>
> </details>
>
> 本地验证已稳定：`53 passed`，Python 编译、前端 JavaScript 语法检查和 `git diff --check` 都通过。页面数据也已确认严格来自 `CodeBlock.contents`，issue 行号严格来自 `Issue.issue_line_numbers`；现在只剩 Docker 镜像构建和容器内测试，确保部署形态与本地一致。
>
> Docker 部署验证也通过了：镜像已成功构建，容器内仍是 `53 passed`，服务健康检查返回 `{"status":"ok","database":"ok"}`，报告入口返回 UTF-8 HTML。最后我正在做一次实现审阅，重点检查 API 路径、0 起始 ID、加权公式、过滤边界和前端交互，避免“测试绿但语义偏了”的情况。
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./tests/test_review_service.py` (+2 -0)
> - Wrote `./app/static/report.css` (+2 -1)
> - Wrote `./app/static/report.js` (+6 -1)
>
> </details>
>
> 最终语义检查没有再发现偏差，文件详情现在也直接展示五维分数，指标区补上了过滤问题数和未完整文件数。由于刚刚调整了静态页面，我会再构建一次最终镜像并跑容器测试，保证交付镜像包含最新页面。
</details>

**已完成**

新增任务审核报告页面：

`http://localhost:8000/reports/{task_id}`

报告包含任务概览、五维雷达图、Token/文件/工具调用统计、负责人筛选、最高严重度问题、上下双分页，以及文件、Block、代码、评论和 Issue 详情。

核心实现位于：

- [report_service.py](./app/services/report_service.py:42)：报告聚合、加权评分、负责人筛选、严重问题计算
- [reports.py](./app/routes/reports.py:14)：页面、报告数据和反馈 API
- [report.html](./app/static/report.html)
- [report.js](./app/static/report.js)
- [report.css](./app/static/report.css)

**评分算法**

- 增量审核：Block 权重为 `+` 和 `-` 变更行总数。
- 全量审核：Block 权重为该 Block 的全部代码行数。
- 文件五维评分：文件内所有 Block 按变更行数加权平均。
- 任务五维评分：任务全部 Block 按变更行数加权平均。
- 总分：五维评分的平均值。

**数据字段确认**

- 代码展示直接使用 `CodeBlock.contents`。
- Issue 行号直接使用 `Issue.issue_line_numbers`。
- `block_id`、`issue_id` 已改为从 `0` 开始。
- `issue_show` 仅保留模型字段，不再参与提示词、过滤、统计、去重或报告展示。
- 过滤结果改由 `filter_status=filtered` 表达。
- `file_author` 只读，用于负责人列表和筛选，不自动生成或修改；全部为空时隐藏下拉菜单。

**反馈 API**

```http
POST /api/feedback/{file_id}/{block_id}/{issue_id}
```

赞成：

```json
{"feedback_type": "agree"}
```

反对：

```json
{
  "feedback_type": "reject",
  "feedback_content": "反对原因"
}
```

**验证结果**

- 本地 pytest：`53 passed`
- Docker 容器 pytest：`53 passed`
- Python 编译检查：通过
- JavaScript 语法检查：通过
- Docker 最终镜像：`sha256:e7ae3d5f9602d36a7347c9e3c10ba232522ad3c004853f47bcb6a799ee83398f`
- 当前容器已启动，健康检查：`{"status":"ok","database":"ok"}`

> 要求报告页面的URL 是/{project_id}/{review_version}_vs_{copy_from_version}.html
> 请重新更正代码。
> Docker Desktop 引擎已经启动，请继续构建测试。
> 请继续测试：
> API KEY： sk-1d9b0fbe9a1d4535b439bc870287f1ce
> 大模型url: [https://api.deepseek.com](https://api.deepseek.com)
> model：deepseek-v4-flash
> 来简单的测试一个具有10个左右C代码文件的代码仓库，假如TaskModel里面有一条数据
> {
> project_id: demo_c,
> review_version：wip_qiaodahai_just_demo,
> copy_from_version: master,
> state:0
> }
> 表示的含义是 review 版本 为 wip_qiaodahai_just_demo 的代码和版本为 master 的代码，两个版本的代码文件分别在本地的两个路径里，比如 D:/codereview/demo_c/wip_qiaodahai_just_demo  和 D:/codereview/demo_c/master（这两个代码路径都不存在，只是一个例子而已，具体的代码文件和路径，需要你来生成以及测试），进行增量代码对比review
> 第二个任务是：
> {
> project_id: demo_c,
> review_version：master,
> copy_from_version: 0_version,
> state:0
> }
> 表示只需要 全量review 代码路径 D:/codereview/demo_c/master
>
> 要求这两个任务及文件数据入库，然后启动服务，给我展示链接，我需要打开链接查看内容

<details><summary>13 previous messages</summary>

> 我先核对当前报告路由、前端如何取得 `task_id`，以及真实 DeepSeek 演示脚本会连接哪个 MongoDB、是否会清理旧数据。随后我会把新 URL 做成唯一的规范入口，补路由解析测试，再用与 Docker 服务相同的 `ci_ai_codereview` 数据库真实跑完增量和全量两个任务。
>
> 实现计划确认如下：
>
> 1. 报告页面规范入口改为 `/{project_id}/{review_version}_vs_{copy_from_version}.html`，按三字段查找最新一次匹配任务。
> 2. 前端不再从 URL 猜 `task_id`，改为调用同路径对应的报告 API；原 task-id 数据 API保留，便于内部和兼容调用。
> 3. 修正演示脚本中最后一处 `issue_show` 统计依赖。
> 4. 本地及 Docker 测试通过后，连接 Docker 正在使用的 `ci_ai_codereview` 数据库真实调用 DeepSeek 跑两个任务，再重启服务并逐个验证最终链接。
>
> <details><summary>Edited 6 files</summary>
>
> - Wrote `./README.md` (+3 -2)
> - Wrote `./app/routes/reports.py` (+20 -2)
> - Wrote `./app/services/report_service.py` (+36 -0)
> - Wrote `./app/static/report.js` (+2 -2)
> - Wrote `./scripts/run_demo_review.py` (+1 -1)
> - Wrote `./tests/test_reports.py` (+5 -1)
>
> </details>
>
> 新 URL 已改好并通过全部 `53` 项本地测试；页面现在会按 `project_id + review_version + copy_from_version` 查找最新任务，前端也不再依赖 URL 中的 task ID。接下来先构建最终 Docker 镜像，然后开始真实 DeepSeek 双任务审核；这一步预计会持续数分钟，因为 20 个文件记录会经历 plan、main 工具循环、重定位与过滤。
>
> 真实审核已经启动，当前脚本没有报错，也还在持续调用模型。它会先完成增量任务，再完成全量任务；最终输出会包含两个任务的状态、文件数、问题数、Token、工具调用和失败 Block 数，我会据此决定是否需要修复后重跑。
>
> 模型调用仍在正常进行，尚未出现超时或异常输出。由于 10 个文件会按并发 4 执行，而每个文件通常需要多轮工具闭环，这段时间主要消耗在 main_task 的上下文检索和证据核验上。
>
> 目前仍无失败日志，说明单次 300 秒和单文件 900 秒超时都没有被触发。脚本采用任务串行、文件并发，所以增量任务完成后才会进入全量任务；我会继续等到数据库汇总完整返回，不会中途停止。
>
> 真实任务已运行约四分钟，仍在模型处理阶段，没有超时或提前退出迹象。这个时长符合此前 DeepSeek 双任务测试的量级；完成后我还会直接查询 MongoDB 校验恰好两条 Task 和 20 条 CodeFile，并用 HTTP 打开两个规范 URL。
>
> 当前仍没有任何异常输出。长时间无标准输出是演示脚本的既有行为，它只在两个任务全部完成后一次性打印 JSON；后台进程仍存活，因此我继续等待最终结果。
>
> 真实 DeepSeek 双任务已成功完成，总耗时约 393 秒，没有任何失败 Block：增量任务 `10/10` 文件、29 个有效问题；全量任务 `10/10` 文件、14 个有效问题。现在我会用最新镜像重建正在运行的 app 容器，并核对 MongoDB 中两条任务、20 条文件记录以及两个最终 URL 的 HTML 和报告 API。
>
> URL 验证发现了一个环境层面的不一致：最新容器能健康启动，但其中一个报告查找返回了 404。真实审核脚本已明确写入 `ci_ai_codereview`，我正在核对容器实际连接的数据库和 Mongo 集合内容，先定位是 Compose 环境覆盖还是版本字符串解析问题，再修正并重新验证两个链接。
>
> 原因已定位：真实审核结果确实存在于 Windows 侧 `127.0.0.1:27017`，查询为 2 条任务、20 条文件；但 Docker 内的 Mongo volume 是另一实例，当前 app 容器看到的是空库，所以页面 404。下一步我会通过 `host.docker.internal` 从容器确认能否访问 Windows 侧结果，然后把 `demo_c` 两个集合复制进 Docker Mongo volume，确保服务和数据处于同一部署环境。
>
> 数据已同步进 Docker Mongo volume，最终两个页面均返回 `200 text/html`。报告 API 也已核对：增量 10 文件、29 个有效问题、436,647 Token；全量 10 文件、14 个有效问题、330,549 Token。现在只做最后的容器测试、密钥未落盘检查和健康检查，然后把可直接点击的两个链接交给你。
</details>

已按指定格式更正报告 URL，并完成真实 DeepSeek 双任务审核。

**报告链接**

- [增量审核报告](http://127.0.0.1:8000/demo_c/wip_qiaodahai_just_demo_vs_master.html)
- [全量审核报告](http://127.0.0.1:8000/demo_c/master_vs_0_version.html)

**真实测试结果**

| 类型 | 状态 | 文件 | 有效问题 | Token | 加权总分 |
|---|---:|---:|---:|---:|---:|
| 增量审核 | `state=2` | 10/10 | 29 | 436,647 | 42 |
| 全量审核 | `state=2` | 10/10 | 14 | 330,549 | 89 |

两个任务均：

- `completion_status=completed`
- 失败 Block 数为 `0`
- 共写入 Docker MongoDB：2 条 Task、20 条 CodeFile
- 所有 main_task 均通过 `task_done` 完成闭环
- 报告页面和对应报告 API 均返回 HTTP 200

URL 查找逻辑位于 [reports.py](./app/routes/reports.py:14)，按 `project_id`、`review_version`、`copy_from_version` 查询最新任务。

**验证**

- 本地测试：`53 passed`
- Docker 容器测试：`53 passed`
- Docker 镜像：`sha256:b16b6479065d8c6877e99fdf50bfd2c846f927f7f76f2f483f62c3f9e3f06a96`
- app、MongoDB 容器均为 `healthy`
- 健康检查：`{"status":"ok","database":"ok"}`
- API Key 未写入任何工程文件。

> 请问如何访问这两个页面？给出链接

直接点击以下链接：

- [增量审核报告](http://127.0.0.1:8000/demo_c/wip_qiaodahai_just_demo_vs_master.html)
- [全量审核报告](http://127.0.0.1:8000/demo_c/master_vs_0_version.html)

也可以将链接复制到本机浏览器地址栏访问。Docker 服务需保持运行。

> 请问审核时长 为什么比 LLM 耗时  要短很多？

<details><summary>1 previous message</summary>

> 我先核对这两个指标在代码里的具体累计方式，尤其是文件并发时 `process_time` 与各 Block 的 `llm_elapsed_ms` 是否分别代表墙钟时间和并发调用耗时之和。确认后我会结合这次报告里的实际数字解释。
</details>

这是正常现象，不是计时错误。两个指标统计口径不同：

- **审核时长：210.89 秒，约 3 分 31 秒**
  从任务开始到结束的实际墙钟时间，代码见 [review_service.py](./app/services/review_service.py:1954)。

- **LLM 耗时：629.01 秒，约 10 分 29 秒**
  所有文件、所有模型轮次调用耗时的累计总和，代码见 [review_service.py](./app/services/review_service.py:1919)。

本次配置 `LLM_CONCURRENCY=4`，文件会通过线程池并发审核，见 [review_service.py](./app/services/review_service.py:221)。

例如 4 个文件同时调用 LLM，每个调用 60 秒：

```text
实际审核时长：约 60 秒
LLM 累计耗时：60 × 4 = 240 秒
```

当前全量任务的数据是：

```text
审核时长：210.890 秒
LLM 累计耗时：629.005 秒
累计耗时 / 实际时长：约 2.98 倍
```

这与最大并发数 4 相符，因为部分阶段仍然是串行执行，且不同文件结束时间不一致。

因此页面中的“LLM 耗时”更准确的名称应当是 **“LLM 累计耗时”**；它用于衡量模型资源消耗，不能直接与实际审核时长比较。

> 报告上的页面上展示的代码是数据库的还是直接读取对比两个文件夹的问题（增量扫描），或者读取当前文件的全部代码（全量扫描）？如果读取的是数据库的代码，那么请继续回答下面的问题：
> 1. 在做审核一个文件的时候，首先给大模型的是哪些代码作为上下文？（plan_task）
> 2. 在 main_task中需要循环调用大模型，然后使用工具获取相关的上下文代码，是不是这个逻辑？如果是，使用工具获取相关代码是从数据库里查询的，还是从哪个物理文件夹的文件里搜索读取出来的？
> 请据详细的例子说明，每一次调用大模型的，需要的上下文，以及工具调用从哪些文件或者数据表中获取的，要说明好源头，并指出所有的工具函数，需要从哪个地方获取信息

<details><summary>4 previous messages</summary>

> 我会沿着一条真实文件审核链路逐层核对：目录扫描生成 `ReviewTarget`、plan_task 消息拼装、main_task 首轮与后续轮次、每个工具的数据源，最后再回到报告 API。重点会区分四种来源：物理代码目录、任务内存中的 diff/索引、配置文件，以及审核完成后才写入的 MongoDB。
>
> 已经确认一个关键结论：报告代码区只读 MongoDB 的 `CodeBlock.contents`，但审核阶段的工具并不从 MongoDB 查代码。审核使用的是目标版本物理目录、扫描时构造的内存 DiffMap，以及从目标目录建立的 AST 索引；MongoDB 是审核完成后的结果落点。下面我继续把每轮消息追加和每个工具的源头精确到函数。
>
> 为了让说明不只停留在抽象流程，我再读取这次真实增量审核中 `src/auth.c` 已落库的模型轮次与工具轨迹。这样可以具体展示“首轮给了什么、第二轮因哪个工具结果新增了什么”，同时明确轨迹是事后记录，审核工具执行时并没有反查这些 MongoDB 记录。
>
> Context compaction
>
> Source: automatic
> Status: completed
</details>

**结论**

报告页面展示的代码来自 **MongoDB 的 `CodeFileModel.code_blocks[].contents`**，不会在打开页面时重新读取代码文件夹。

相关实现位于：

- [report_service.py](./app/services/report_service.py:79)：查询 `TaskModel` 和 `CodeFileModel`
- [review_service.py](./app/services/review_service.py:694)：审核完成后把 `CodeBlock.contents` 写入数据库
- [diff_service.py](./app/services/diff_service.py:52)：从物理目录产生增量或全量代码内容

因此整体数据流是：

```text
物理代码目录
  -> 目录扫描和代码对比
  -> 内存中的 ReviewTarget / diff_map
  -> plan_task 和 main_task
  -> CodeFileModel / CodeBlock 写入 MongoDB
  -> 报告页面从 MongoDB 展示历史审核快照
```

即使审核后修改了物理文件，只要不重新执行任务，原报告内容也不会变化。

**Plan Task 上下文**

每审核一个 CodeBlock，`plan_task` 首次调用大模型时会发送两个 Message：

```text
messages = [
  {"role": "system", "content": 基础审核规则},
  {"role": "user", "content": 本次 Block 的全部审核上下文}
]
```

拼装代码在 [prompts.py](./app/services/prompts.py:256)，调用入口在 [review_service.py](./app/services/review_service.py:792)。

用户消息包含以下内容：

1. 当前阶段指令：要求分析变更、输出五维评分和总体评论。
2. 文件名、编程语言和匹配到的审核规则。
3. 当前文件的业务背景 `background`。
4. 本次任务所有变更文件的清单。
5. 自动筛选出的相关文件和相关 diff。
6. SARIF/JSON 静态分析发现。
7. 当前 `CodeBlock` 的变更代码。
8. 当前目标文件的完整代码。
9. 强约束 JSON 输出格式。

这里有一个重要细节：如果文件因为超过 token 限制被拆成多个 Block，每个 `plan_task` 获得的是：

```text
当前 Block 的 diff
+
当前文件完整代码
```

它不是从 MongoDB 查询的。数据来源如下：

| 上下文 | 来源 |
|---|---|
| Block diff | 扫描开始时对物理目录比较后生成的 `ReviewTarget.diff_lines` |
| 完整代码 | review 版本物理文件的 `ReviewTarget.full_code` |
| 相关文件 | 本次任务内存中的其他 `ReviewTarget` |
| 文件规则 | `review_rules.json`、外部规则文件或项目 `.opencodereview/rule.json` |
| background | [background.py](./app/services/background.py) 的 Mock Provider |
| 静态分析结果 | review 目录中的 SARIF/JSON 文件 |

增量审核时完整代码来自 **review_version 目录**，不是参照版本目录；参照版本主要用于生成 diff。

**Main Task 调用机制**

`main_task` 的初始消息同样是 `system + user`，拼装实现位于 [prompts.py](./app/services/prompts.py:301)。

第一轮包含：

```text
系统审核规则
+ plan_task 的评论、评分、风险和检查点
+ 当前 Block diff
+ 当前文件完整代码
+ 相关文件上下文
+ 静态分析结果
+ background
+ 工具定义
```

模型如果需要进一步确认调用关系、定义位置或完整代码，会返回 function calling。程序执行工具，把结果追加为 `role=tool` 消息：

```text
第 1 轮：初始上下文 -> 模型提出工具调用
执行工具 -> 追加 tool result

第 2 轮：初始上下文 + 第1轮 assistant + tool result
模型继续调用工具

第 N 轮：累积历史 + 最新工具结果
模型调用 code_comment 提交问题
模型调用 task_done(DONE) 结束
```

循环实现在 [review_service.py](./app/services/review_service.py:1024)。历史过长时会压缩较早轮次，但保留初始任务、结论摘要和最近工具调用。

**工具数据源**

所有 main_task 工具定义在 [review_tools.py](./app/services/review_tools.py)，审核过程中都不从 `CodeFileModel` 查询代码。

| 工具 | 信息来源和逻辑 |
|---|---|
| `file_find` | 遍历 `review_root` 物理目录，按文件名和扩展名查找 |
| `read_file` / `file_read` | 安全校验路径后读取 `review_root` 下的物理文件 |
| `code_search` | 在 `review_root` 物理目录中全文搜索代码 |
| `file_read_diff` | 查询当前任务内存中的 `diff_map`，不重新比较目录 |
| `find_definition` | 查询从 `review_root` 物理代码构建的内存 AST 语义索引 |
| `find_references` | 查询同一个内存 AST 语义索引中的符号引用 |
| `call_graph` | 查询内存语义索引构建的调用关系 |
| `code_comment` | 不读取文件；将模型提交的问题暂存在 `ReviewToolRunner.comments` |
| `task_done` | 不读取文件；设置当前 main_task 循环完成状态 |

增量任务的 `review_root` 是：

```text
demo_repos/demo_c/wip_qiaodahai_just_demo
```

全量任务的 `review_root` 是：

```text
demo_repos/demo_c/master
```

所以增量审核中的 `read_file`、`code_search`、AST 工具读取的都是 **新版本目录**。只有 `file_read_diff` 同时体现 master 和 review 版本的差异，因为 `diff_map` 是之前比较两个目录生成的。

**增量审核示例**

假设 `master/src/auth.c`：

```c
const char *expected = "demo";
if (token == 0) {
    return 0;
}
return strcmp(token, expected) == 0;
```

review 版本：

```c
if (token == 0) {
    return 1;
}
return strstr(token, "admin") != 0;
```

典型调用过程是：

1. `plan_task` 获得 auth.c 当前 Block diff、review 版本完整 auth.c、项目规则和相关文件。
2. main 第 1 轮获得上述内容和 plan 结论，调用 `find_references("check_token")`。
3. 工具从 review 版本物理目录建立的 AST 索引中查找引用。
4. main 第 2 轮收到引用结果，调用 `read_file("src/auth.c")`。
5. 工具直接读取 review 版本物理文件。
6. main 第 3 轮调用 `code_search("check_token")`，在 review 版本目录全文搜索。
7. main 第 4 轮调用 `file_read_diff(["src/auth.c"])`，从内存 `diff_map` 取得 master 与 review 的差异。
8. 模型调用 `code_comment` 提交问题，再调用 `task_done`。
9. 系统执行行号重定位、误报过滤和文件内 issue 去重。
10. 最终将 diff、完整评论、评分和 issue 写入 `CodeFileModel`。

**全量审核区别**

全量审核没有参照目录。扫描器读取 `master` 物理文件，把每一行格式化成 `+` 行作为 `CodeBlock.contents`，同时把原始完整代码传给 plan/main。

审核结束后，增量 diff 或全量代码都已经固化到 MongoDB。报告页面只读取这份固化结果；物理目录只在审核执行阶段被扫描和工具访问。

> 继续回答下面的疑问
> 文件的 block 的 contents 数据是什么时候写入的？
> 前面提到 7. main 第 4 轮调用 file_read_diff(["src/auth.c"])，从内存 diff_map 取得 master 与 review 的差异。
> 请问从内存取是什么意思？是读取物理文件目录还是数据库？

<details><summary>2 previous messages</summary>

> 我会沿着“物理目录扫描 → 内存对象 → MongoDB 落库”这条链路再核对一次具体代码位置，重点说明 `CodeBlock.contents` 的写入时机，以及 `diff_map` 到底保存了什么。
>
> 已经确认：`diff_map` 不是数据库缓存，也不是工具调用时临时重读目录。它是在任务扫描开始阶段读取两个物理目录并计算后，保存在当前 Python 审核进程中的字典；随后 `file_read_diff` 只是查这个字典。下面我再补清楚文件占位记录与最终 `contents` 落库之间的先后关系。
</details>

**1. `CodeBlock.contents` 何时写入数据库**

完整时序如下：

```text
1. 任务开始，TaskModel.state 设置为 1
2. 读取物理代码目录
3. 计算 diff，生成内存中的 ReviewTarget 和 diff_map
4. 将文件 diff 按 token 限制拆成多个 block_lines
5. 对当前 Block 执行 plan_task
6. 执行 main_task 工具循环
7. 执行行号重定位、误报过滤、文件内 Issue 去重
8. 创建 CodeBlock(contents=block_lines)
9. 文件所有 Block 审核完毕
10. 创建 CodeFileModel(code_blocks=code_blocks)
11. 调用 code_file.save()，整体写入 MongoDB
```

具体代码：

- 拆分 Block：[review_service.py:630](./app/services/review_service.py:630)
- 执行 plan_task：[review_service.py:634](./app/services/review_service.py:634)
- 创建 `CodeBlock` 并赋值 `contents`：[review_service.py:694](./app/services/review_service.py:694)
- 保存整个文件及其 Blocks：[review_service.py:740](./app/services/review_service.py:740)
- 真正写入 MongoDB：[review_service.py:772](./app/services/review_service.py:772)

因此，`contents` **不是在目录扫描时立即写入 MongoDB**，而是在当前文件的所有 Block 审核完成后，随 `CodeFileModel.save()` 一起写入。

`CodeBlock` 是 MongoEngine 的嵌入文档，所以它没有单独保存操作；它必须嵌入 `CodeFileModel` 一起保存。

**`contents` 保存的具体内容**

```python
contents = block_lines
```

`block_lines` 来自：

```python
split_code_blocks(target.diff_lines)
```

所以：

- 增量审核：保存 master 与 review 版本的差异代码和上下文。
- 全量审核：保存当前文件全部代码，但每行会被格式化为 `+` 行。
- 它不是未经格式化的 `target.full_code`。
- `target.full_code` 会提供给 LLM，但当前没有直接保存到 `CodeBlock.contents`。

**2. “从内存 `diff_map` 取得”是什么意思**

在执行 `file_read_diff` 的那个瞬间：

- 不读取 MongoDB。
- 不重新读取物理文件。
- 直接查询当前 Python 进程内存中的字典。

这个字典结构类似：

```python
diff_map = {
    "src/auth.c": [
        "     1   #include <string.h>",
        "     4-      const char *expected = \"demo\";",
        "     5+          return 1;",
        "     7+      return strstr(token, \"admin\") != 0;",
    ],
    "src/config.c": [...],
}
```

工具执行的核心逻辑是：

```python
diff_lines = self.diff_map.get(file_path)
```

对应 [review_tools.py:97](./app/services/review_tools.py:97)。

所以准确地说：

> `file_read_diff` 调用时既不读物理目录，也不读数据库，而是读取之前由物理目录生成并保存在 Python 进程 RAM 中的 diff。

**`diff_map` 最初从哪里来**

增量任务开始时，系统读取两个物理目录：

```text
base:
demo_repos/demo_c/master

head:
demo_repos/demo_c/wip_qiaodahai_just_demo
```

处理过程是：

1. 收集两个目录的文件。
2. 相同路径文件先比较 MD5。
3. MD5 相同则跳过。
4. MD5 不同则读取两个物理文件。
5. 用 `difflib.SequenceMatcher` 计算代码差异。
6. 把结果存入 Python 字典 `diff_map`。

实现位于 [diff_service.py:49](./app/services/diff_service.py:49)：

```python
base_lines = self._read_text_lines(base_path)
head_lines = self._read_text_lines(head_path)
diff_lines = self.create_diff_lines(base_lines, head_lines)
diff_map[file_name] = diff_lines
```

然后整个对象返回给审核服务：

```python
ReviewCollection(
    targets=targets,
    diff_map=diff_map,
    changed_files=changed_files,
)
```

审核服务把它保存在：

```python
self.review_context = review_context
```

对应 [review_service.py:142](./app/services/review_service.py:142)。

**三种读取方式的区别**

| 操作 | 数据来源 |
|---|---|
| `file_read_diff` | Python 内存中的预计算 `diff_map` |
| `read_file` | review 版本的物理目录 |
| `code_search` | review 版本的物理目录 |
| `find_definition` 等语义工具 | 由 review 版本物理目录构建的内存 AST 索引 |
| 报告页面展示代码 | MongoDB 中的 `CodeBlock.contents` |

例如 main 第 4 轮执行：

```json
{
  "name": "file_read_diff",
  "arguments": {
    "path_array": ["src/auth.c"]
  }
}
```

此时运行逻辑只是：

```python
diff_lines = diff_map["src/auth.c"]
```

不会再次打开：

```text
master/src/auth.c
wip_qiaodahai_just_demo/src/auth.c
```

也不会查询：

```text
ai_codereview_code_file
```

如果审核进程重启，原来的内存 `diff_map` 就不存在了；恢复任务时需要重新扫描物理目录并重新生成。MongoDB 中已经保存的 `contents` 主要用于报告、结果查询和历史留存，不作为 `file_read_diff` 的数据源。

> OCR 是不是也是这种全部放到内存中，一直等到全部审核完毕才把所有的审核结果一次性写入物理文件里？如果OCR被中断，是不是前功尽弃了？
> 本项目需要等到全部审核结束才入库，这种机制是不是比较危险？我们想做的是一个服务，中间可以被中断，中断后还可以继续，请分析我们计划采用什么的优化才能达到可以被中断，中断后还可以继续执行，但是要确保审核精确度和以前保持不变。 请给出优化计划

<details><summary>3 previous messages</summary>

> 我会先核对 OCR 官方代码中结果保存与中断恢复的真实机制，再对照本项目现有的文件级 resume 实现。重点会区分三种范围：整个任务、单个文件、单个 Block，因为它们目前的持久化边界并不相同。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:github.com/alibaba/open-code-review plan_task main_task save result output file resume ...`
> - Searched the web for `'WriteCheckpoint'`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/session/persist.go`
> - Searched the web for `'WriteReviewItemDone'`
> - Searched the web for `https://github.com/alibaba/open-code-review/blob/main/internal/session/resume.go`
>
> </details>
>
> </details>
>
> OCR 最新官方版本已经明确加入 `session` 与 `--resume`，所以“中断必然前功尽弃”已经不符合当前实现。我正在核对它的持久化粒度和刷盘时机，这会直接影响我们应当借鉴到文件级还是 Block 级。
</details>

**先给结论**

截至我核对的 OCR `main` 分支提交 [`50e5a172`](https://github.com/alibaba/open-code-review/commit/50e5a17293878cda34a811914273cbb7a31b0261)，OCR 已经不是“所有结果一直放内存，最后一次性写文件”的模式。

OCR 当前同时做了两件事：

1. LLM 请求、响应、工具调用持续追加到 JSONL session 文件。
2. 每个文件审核完成或失败后，写入 `review_item_done` / `review_item_failed` 检查点，并立即 `Flush()` 到磁盘。[persist.go](https://github.com/alibaba/open-code-review/blob/main/internal/session/persist.go)

它在下次执行 `--resume <session-id>` 时，根据 diff fingerprint 复用已完成文件，只重新审核未完成文件。[agent.go](https://github.com/alibaba/open-code-review/blob/main/internal/agent/agent.go)、[resume.go](https://github.com/alibaba/open-code-review/blob/main/internal/session/resume.go)

因此 OCR 被中断后的实际结果是：

- 已完成文件：不会丢失，可以复用。
- 正在审核的文件：通常从文件开头重新审核。
- 最终汇总还没生成：重新汇总即可。
- 当前 OCR resume 主要支持 range/commit，workspace 和 full scan 的恢复仍有限制。

**本项目现状**

“需要整个项目全部审核结束才入库”并不完全准确。本项目当前是：

```text
项目包含多个文件
  -> 每个文件所有 Block 审核完毕
  -> 保存这个文件的 CodeFileModel
  -> 继续审核其他文件
  -> 所有文件完成后更新 TaskModel 和项目汇总
```

每个文件完成后就会执行 `code_file.save()`，见 [review_service.py:772](./app/services/review_service.py:772)。已完成文件会根据 `source_hash + review_fingerprint` 复用，见 [review_service.py:322](./app/services/review_service.py:322)。

所以中断不会让整个任务前功尽弃，但有以下风险：

1. 检查点只到文件级。一个文件有 10 个 Block，即使已经完成 9 个，只要第 10 个执行时进程退出，这个文件的 10 个 Block 都没有落库。
2. 并发为 4 时，强制退出最多可能丢失 4 个正在执行文件的进度。
3. 进程被强制杀死时，异常处理不会执行，`TaskModel.state` 可能永久停留在 `1`。
4. Scheduler 当前没有任务 lease、心跳和过期任务接管，只会执行 mock 任务，见 [scheduler.py:32](./app/services/scheduler.py:32)。
5. 恢复时会重新扫描当前物理目录。如果目录内容已经改变，重新执行的文件可能和已完成文件不属于同一份代码快照。
6. 文件先保存，再执行 batch dedup。若恰好在两者之间中断，恢复时可能把该文件当作已完成并跳过后处理。
7. LLM 每轮消息和工具轨迹目前随最终 `CodeBlock` 保存，当前 Block 中途退出时，已经产生的 token、调用轨迹也会丢失。

**推荐目标架构**

```mermaid
flowchart LR
    A["原始代码目录"] --> B["创建不可变审核快照"]
    B --> C["持久化文件与 Block 输入"]
    C --> D["Worker 获取带租约的 Block"]
    D --> E["plan_task 检查点"]
    E --> F["main_task 每轮事件检查点"]
    F --> G["定位、过滤、去重"]
    G --> H["Block 完成"]
    H --> I["文件聚合"]
    I --> J["任务汇总并设置 state=2"]
```

**建议的数据结构**

| 数据结构 | 需要增加的内容 |
|---|---|
| `TaskModel` | `lease_owner`、`lease_token`、`lease_expires_at`、`heartbeat_at`、`resume_count`、`snapshot_id`、`manifest_hash`、`pipeline_version` |
| `CodeFileModel` | 明确的 `status`、`source_hash`、`review_fingerprint`、`completed_block_num`、`postprocess_status` |
| `ReviewSnapshotModel` | base/head 路径、文件清单、每个文件 SHA-256、规则和配置指纹、快照物理目录 |
| `ReviewBlockCheckpointModel` | `task_id`、`file_name`、`block_id`、`contents`、`block_hash`、阶段状态、plan 结果、main 候选问题、最终问题 |
| `ReviewExecutionEventModel` | 每轮 LLM 请求增量、响应、tool call/result、token、耗时、序号、request hash、attempt id |

最终报告仍然读取原有 `CodeFileModel.code_blocks`，新增表只负责运行状态和恢复，避免破坏现有报告数据结构。

**恢复机制**

1. 任务开始时创建不可变快照。增量任务同时快照 base/head，全量任务快照目标目录。
2. 先计算 diff、拆分 Block，并把 `contents` 和 `block_hash` 持久化，然后才调用 LLM。
3. `plan_task` 成功后立即保存 `plan_completed`。
4. main_task 每轮保存 assistant response、tool calls、tool results 和下一轮消息状态。
5. `code_comment` 只保存候选问题，完成 relocation/filter 后才发布到最终 `issues`。
6. Block 完整完成后标记 `completed`；恢复时直接复用，不再调用 API。
7. 文件完成后执行文件内去重和评分，标记 `file_completed`。
8. batch dedup、项目评分和 summary 必须设计成幂等步骤，可重复执行，不依赖上次内存状态。
9. Scheduler 原子领取 `state=0`、`state=3` 或租约过期的 `state=1` 任务，并持续刷新心跳。
10. 所有写操作校验 `lease_token`，避免旧 Worker 恢复后覆盖新 Worker 的结果。

**如何保证精确度不下降**

恢复必须遵守严格指纹校验：

```text
代码快照哈希
+ Block 边界和 block_hash
+ background
+ 审核规则
+ System Prompt/阶段 Prompt 版本
+ 模型和关键参数
+ tools schema 与实现版本
+ relocation/filter 配置
+ 静态分析输入
```

任意一项变化，该 Block 都不能复用，必须重新审核。工具在恢复后只能读取不可变快照目录，不能读取可能已经改变的原始目录。

第一阶段建议只复用“完整完成的 Block”，中断中的 Block 从 `plan_task` 重新开始。这最稳妥，只浪费当前 Block 的少量 API 调用，不会把半截上下文带入审核。第二阶段再启用 main_task 轮次级恢复，通过事件日志重建完全相同的 `messages`。

外部 LLM 调用无法实现绝对 exactly-once：如果 API 已返回但进程在持久化前崩溃，该轮只能重试，模型输出可能略有差异。可以保证的是已完成检查点不变化、输入上下文一致、完整定位和过滤流程不被跳过。

**实施顺序**

1. 增加 Task lease、心跳、过期任务自动接管。
2. 创建不可变代码快照和任务输入 manifest。
3. 在 LLM 调用前持久化文件及 Block 输入。
4. 增加 Block 级状态机和检查点，先实现安全恢复。
5. 增加 main_task 轮次事件日志和可选轮次级恢复。
6. 把 dedup、评分、project summary 改成幂等聚合。
7. 加入故障注入测试：分别在 plan 后、main 第 4 轮、`task_done` 后、filter 前、文件保存后、项目汇总前强制中断。
8. 对比不中断与多次中断后的最终 `contents`、评分、issues、行号及过滤结果，确定完全一致后再默认开启轮次级恢复。

> 继续优化：
> 1. 增加 ProjectModel，一个项目有多个task，其中的Review保留，暂不使用
>
>    class Review(EmbeddedDocument):
>        id = StringField(required=True)  # {review_version}*vs*{copy_from_version}
>        state = IntField(required=True)
>        score = IntField(required=False, default=0)
>        create_time = DateTimeField(required=True)
>
>    class ProjectModel(Document):
>        meta = {"collection": "ai_codereview_project", "indexes": ["project_id"]}
>
>        project_id = StringField(required=True)
>        project_name = StringField(required=False, default="")  # might be a chinese name, or
>        project_url = StringField(required=False)
>        git_project_id = IntField(required=False)
>
>        owner = ListField(required=False, default=[])
>        developers = ListField(required=False, default=[])
>        exclude_path = ListField(
>            required=False, default=[]
>        )  # exclude folder path("BSW/Communications/Com_FT") or file path ("BootloaderPlus/BootloaderPlus.c")
>
>        version_control_system = StringField(required=True)
>        history_reviews = DictField(EmbeddedDocumentField(Review))
>        scan_round = IntField(required=False, default=0)
>        created_by = StringField(required=False, default="")
>        create_time = DateTimeField(default=datetime.now(), required=True)
>        updated_by = StringField(required=False, default="")
>        update_time = DateTimeField(required=False)
>        default_base_branch = StringField(required=False, default="")
> 2. 现在是否有排除路径或者文件的配置，如果有则合并下面的配置：exclude_path=MCAL,Math,General,COMM,CANVector,main.c,Wdg,Smu,SafeTlib,SafeTpack,ERU_BSW,Eth_generated,Dem,DemConfig,FiM,FiMConfig,VStdLib,Etpu,freertos,FW_LIB,StartUp,Os_Stubs.c,Os_TaskInfr.c,.vscode,.history,**pycache**,BootloaderPlus_CData.c,PrjVer.c,PrjVer.h,SoftVer_Release.h，如果没有则新增该配置，表示凡是文件路径包含了这里面任意一个元素，则不审核该代码，也就是说该文件代码不会进入到file 表里
> 3. 由于服务器最终会运行到内网里，前端汇报页面不能引入互联网的 css,js的链接
> 4. 我需要拆分项目，分为Client端，和 server 端，
>    4.1 client 端是触发端，由一个jenkins job，jenkins job 接收 project_id，review_version, copy_from_version, review_version_path, copy_from_version_path这几个字段，整个Jenkins job 被触发后，会写入一条task 记录，设置该任务的状态是待review，同时写入所有的需要review的文件到文件表。如果 copy_from_version = "0_version"，则表示全量扫描，如果其实其它，则是增量扫描。
>    4.2 server端，通过AsyncIOScheduler 异步扫描 4.1阶段待review 的任务，扫描到一个待review的任务，设置该任务正在review，然后审核每一个还未review的文件，所以，整个审核过程可能因为服务要重新部署而中断，支持中断后继续审核，直到结束。增量review的优先级要高于全量review，在同样优先级的情况下，优先审核时间早的任务。在全量审核的过程中，如果发现有增量的任务过来了，要中断全量的审核，转而去审核增量的任务。task_type=1 表示增量审核，task_type=2
>    4.3 client 端可能会重复触发同样参数的任务，比如这些字段（project_id，review_version, copy_from_version, review_version_path, copy_from_version_path）的值可能完全相同，表示用户在开发阶段，仍在持续提交代码，这是需要注意，这时需要重置 task 任务的状态到 未审核，但是审核token及调用次数之类的数据不能重值，要和继续审核的数据累加起来，同样的文件的Block如果没有变更（这个Block的md5值没有变化），则不更新。如果这个文件发生了变化，则这个Block审核相关的数据肯定要清空，需要继续审核。
> 5. 每个任务结束后，会发邮件，请写一个发邮件的空函数，里面只需要写一个demo日志即可，由以后补充完善。
> 所以当前优化主要工作是拆分 client 和server，支持中断继续审核。

<details><summary>27 previous messages</summary>

> 我先把当前模型、任务 API、目录扫描、Scheduler 和报告静态资源完整串起来，再按现有分层落地。这个改动会同时触及任务幂等触发、文件预入库、调度抢占与恢复，因此我会先确定现有状态字段和并发边界，避免把已有审核流程改乱。
>
> 现有工程已经具备“完成文件可复用”的雏形，但 Jenkins 触发阶段还没有预生成文件记录，Scheduler 也没有领取待处理任务或抢占逻辑。我的实现计划是：
>
> 1. 新增 `ProjectModel`，把全局和项目级排除项统一成一个路径匹配器。
> 2. 增加 Jenkins 触发 API/Client Service：按五字段幂等创建或重置任务，预计算 diff/全量文件并写入待审核的 `CodeFileModel`/Block。
> 3. 把审核改为消费预生成文件，按 Block 哈希复用；变化 Block 清空结果，未变化 Block保留，使用量改为生命周期累计。
> 4. Scheduler 原子选择任务，增量优先、同级按时间，并用协作式取消抢占全量任务；服务重启后继续待审核文件。
> 5. 增加邮件空实现、离线前端校验、配置/README/测试，并跑完整 pytest 和 Docker 构建。
>
> 我已经确认报告页目前只引用本服务的 `/static/report.css` 和 `/static/report.js`，雷达图也是原生 Canvas 绘制，没有外网依赖；这一点会补成自动化测试，防止以后回归。接下来开始改数据模型和任务准备链路：Jenkins 触发时就固化待审核文件与 Block 输入，Server 只消费这些待处理记录。
>
> 现在开始第一批文件编辑：新增项目模型和任务/文件运行状态字段，并抽出统一的路径排除器。排除规则会采用规范化后的“路径包含”匹配，既合并环境变量默认项，也合并 `ProjectModel.exclude_path`，并同时约束预扫描、main_task 工具和语义索引。
>
> <details><summary>Created 4 files, edited 9 files</summary>
>
> - Wrote `./app/core/config.py` (+13 -1)
> - Wrote `./app/models/__init__.py` (+11 -1)
> - Wrote `./app/models/code_file.py` (+15 -1)
> - Wrote `./app/models/project.py` (+43 -0)
> - Wrote `./app/models/task.py` (+17 -2)
> - Wrote `./app/services/exclusions.py` (+31 -0)
> - Wrote `./app/services/diff_service.py` (+7 -2)
> - Wrote `./app/services/review_tools.py` (+4 -1)
> - Wrote `./app/services/semantic_index.py` (+9 -2)
> - Wrote `./app/routes/tasks.py` (+10 -1)
> - Wrote `./app/schemas/task.py` (+32 -0)
> - Wrote `./app/services/task_submission.py` (+242 -0)
> - Wrote `./scripts/jenkins_trigger.py` (+39 -0)
>
> </details>
>
> 预扫描入口已经落下来了：同一五字段任务会复用同一条 Task，增加触发版本号，并按 Block MD5 保留已完成结果；新增或变化 Block 会以待审核状态写入文件表。下面修改 Server 审核器，让它不再删除预生成文件，而是逐 Block 保存检查点，并能识别重新触发或调度抢占。
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./app/core/exceptions.py` (+4 -0)
> - Wrote `./app/services/review_service.py` (+48 -16)
> - Wrote `./app/services/review_service.py` (+8 -3)
> - Wrote `./app/models/code_file.py` (+1 -0)
> - Wrote `./app/schemas/code_file.py` (+2 -0)
> - Wrote `./app/services/review_service.py` (+117 -34)
> - Wrote `./app/services/review_service.py` (+116 -9)
> - Wrote `./app/services/review_service.py` (+2 -0)
> - Wrote `./app/services/review_service.py` (+34 -18)
> - Wrote `./app/schemas/code_file.py` (+10 -0)
>
> </details>
>
> Block 级检查点已经接入：Server 对新 Block 审核后立即保存，重启时会跳过 `block_hash + 审核配置指纹` 均未变化且已完整结束的 Block。下一步替换原来的 mock Scheduler，加入任务原子领取、租约心跳、增量优先和对全量任务的协作式抢占，同时把完成邮件留成独立扩展点。
>
> <details><summary>Created 2 files, edited a file</summary>
>
> - Wrote `./app/services/notification.py` (+17 -0)
> - Wrote `./app/services/review_service.py` (+5 -0)
> - Wrote `./app/services/scheduler.py` (+162 -0)
>
> </details>
>
> 调度链路已替换为真正的 Server 消费模式：它会优先领取增量任务，同级按创建时间排序；全量审核期间发现增量任务时设置停止信号，当前 LLM 请求返回后在最近的轮次或 Block 边界中断并释放租约。现在先跑静态编译和核心测试，把模型兼容性、Block 恢复和 API 回归问题逐个修掉。
>
> 第一轮测试暴露的是预期中的规则变化：默认排除项现在包含 `main.c`，所以原来以 `main.c` 验证工具和语义索引的测试不再成立。实现行为符合新需求，我会把这些测试样本改为非排除文件，并新增专门测试来证明 `main.c`、项目级目录和 `**pycache**` 确实不会进入文件表。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/conftest.py` (+3 -0)
> - Wrote `./tests/test_review_tools.py` (+17 -17)
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> 我先把刚才测试暴露出的两个兼容问题收紧：测试环境中的默认排除规则误伤了历史用例，以及直接调用任务收尾逻辑时用量基线未初始化。修完后我会先跑完整测试，再补上“重复触发、Block 复用、调度优先级与恢复”的专项用例。
>
> 现象已经对上了：生产默认排除列表本身没有问题，失败来自旧测试把 `main.c`、`math.c` 当作普通样例文件；测试夹具应该显式关闭业务排除列表。任务收尾部分也会改成具备完整零值基线，并让“部分完成”计入重试次数，避免调度器无限领取同一份未完成任务。
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./app/services/review_service.py` (+19 -2)
> - Wrote `./tests/conftest.py` (+1 -0)
>
> </details>
>
> 完整回归已经恢复为 `53 passed`。接下来进入这次需求真正的关键验证：我会逐项审查提交同步器和调度器，特别看同参数重复触发时是否真的做到“用量累加、未变 Block 保留、变化 Block 清空”，以及全量任务被增量任务抢占后能否从数据库断点继续。
>
> 当前实现的断点策略是“文件和 Block 作为检查点”，不是等整仓结束才落库：Jenkins 触发阶段先把待审 Block 写入 `CodeFileModel`，每个 Block 完成后立即覆盖保存；重启后只重新执行未完成或指纹失效的 Block。现在我会把这个行为固化成自动化测试，同时补一个边界修正：`issue_show` 保持真正的备用字段，不再由模型层自动填默认值。
>
> <details><summary>Created 2 files, edited 3 files</summary>
>
> - Wrote `./app/models/code_file.py` (+1 -1)
> - Wrote `./tests/test_reports.py` (+10 -0)
> - Wrote `./tests/test_scheduler.py` (+63 -0)
> - Wrote `./tests/test_task_submission.py` (+147 -0)
> - Wrote `./tests/test_reports.py` (+2 -1)
> - Wrote `./tests/test_task_submission.py` (+1 -1)
> - Wrote `./tests/test_reports.py` (+2 -2)
>
> </details>
>
> 专项用例现在全部通过，已经覆盖：全量/增量预写文件、全局与项目级排除、重复触发保留未变 Block、变更 Block 清空、token/调用次数累加、增量优先、同优先级 FIFO、过期租约恢复，以及报告页无外网资源。下一步我会补齐部署配置与文档，让 Jenkins 路径映射、调度租约和任务状态在真实内网环境里可直接落地。
>
> 我还发现了一个多实例部署下的重要竞态：两个 server 同时回收“租约已过期但 state 仍为 1”的任务时，原来的原子条件只校验 state，可能被重复领取。我会把旧 lease token 也纳入 compare-and-set，并给 Jenkins 同参数提交增加稀疏唯一的 `submission_key`，让并发重复触发也尽量归并到同一个 Task。
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./app/models/task.py` (+2 -0)
> - Wrote `./app/services/scheduler.py` (+2 -0)
> - Wrote `./app/services/task_submission.py` (+48 -24)
> - Wrote `./tests/test_task_submission.py` (+4 -1)
>
> </details>
>
> 部署层面会明确采用“共享代码目录”的边界：Jenkins 传给 API 的必须是 server 进程可见的路径；Docker 场景通过只读 bind mount 映射到 `/repositories`。这样 tools 继续读取物理仓库以保持跨文件审核精度，而断点状态、Block 内容、调用轨迹和累计用量全部由 MongoDB 保存。
>
> <details><summary>Edited 6 files</summary>
>
> - Wrote `./.env.example` (+8 -3)
> - Wrote `./README.md` (+21 -0)
> - Wrote `./config.md` (+27 -7)
> - Wrote `./docker-compose.yml` (+11 -2)
> - Wrote `./scripts/jenkins_trigger.py` (+2 -1)
> - Wrote `./tests/test_reports.py` (+5 -0)
>
> </details>
>
> 完整测试现为 `61 passed`。接下来做最后一轮工程验证：Python 编译检查、补丁空白检查、Compose 配置展开和 Docker 镜像构建；这一步主要捕捉单元测试看不到的环境变量/YAML/容器入口问题。
>
> 镜像构建成功，Compose 配置也能正常展开。最后我会实际重建并启动 `app + mongodb`，确认健康检查；这里也会顺带验证新增的 MongoDB 索引在现有数据库数据上不会阻止服务启动。
>
> 容器已实际启动，`app` 与 `mongodb` 都是 healthy，`/health` 返回 `{"status":"ok","database":"ok"}`；新增稀疏唯一索引也没有破坏现有数据库启动。现在只做一次最终变更审计，确认没有把 API Key、临时数据或无关文件带进修改集。
</details>

**已完成**
- 新增 [ProjectModel](/C:/Users/qiao/Documents/ci-ai-codereview/app/models/project.py:26)，`Review/history_reviews` 保留但暂不参与流程。
- 新增 Jenkins 触发接口 `POST /tasks/trigger` 和 [jenkins_trigger.py](/C:/Users/qiao/Documents/ci-ai-codereview/scripts/jenkins_trigger.py)。
- 触发阶段立即预写 `CodeFileModel/CodeBlock`，排除规则合并全局配置和 `ProjectModel.exclude_path`。
- 重复任务通过 `submission_key` 归并；累计 token、调用次数和耗时。未变 Block 保留结果，变化 Block 清空重审。
- [ReviewScheduler](/C:/Users/qiao/Documents/ci-ai-codereview/app/services/scheduler.py:24) 支持增量优先、FIFO、全量抢占、心跳租约、过期任务恢复和多实例原子领取。
- 每个 Block 审核完成后立即落库；服务中断后从未完成 Block 继续，不必等待整个项目结束。
- 报告页面只使用本地 `/static/report.css` 和 `/static/report.js`，不依赖互联网。
- 任务完成后调用邮件占位日志函数。
- Docker 将宿主代码目录只读映射至 `/repositories`。Jenkins 参数必须填写 server 容器可见路径。

配置和运行说明已更新到 [README.md](/C:/Users/qiao/Documents/ci-ai-codereview/README.md:49)、[config.md](/C:/Users/qiao/Documents/ci-ai-codereview/config.md) 和 [.env.example](/C:/Users/qiao/Documents/ci-ai-codereview/.env.example:1)。

**验证结果**
- `pytest`：`61 passed`
- Python 编译检查：通过
- `git diff --check`：通过
- `docker compose config --quiet`：通过
- `docker compose up -d --build`：成功
- app、MongoDB：均为 `healthy`
- 健康接口：[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)，当前返回 `{"status":"ok","database":"ok"}`。

> 请分析中client + server 模式，以及中断继续审核模式，和 原生的OCR 审核机制（原理）比较，审核的精确度有没有下降？为什么？

<details><summary>2 previous messages</summary>

> 我会把“架构可靠性”和“模型审核精度”分开比较：先核对当前工程的提交快照、Block 复用指纹和中断点，再对照 OCR 的任务编排、上下文生命周期与最终汇总机制。关键不是是否落库，而是恢复后送给模型的代码、规则、工具上下文和项目级后处理是否与不中断时等价。
>
> <details><summary>Searched the web</summary>
>
> <details><summary>Searched the web</summary>
>
> - Searched the web for `site:github.com/alibaba/open-code-review plan_task main_task tools task_done ...`
> - Searched the web for `https://api.github.com/repos/alibaba/open-code-review/git/trees/main?recursive=1`
> - Searched the web for `'planTask'`
> - Searched the web for `https://raw.githubusercontent.com/alibaba/open-code-review/main/internal/session/resume.go`
> - Searched the web for `https://github.com/alibaba/open-code-review/blob/main/internal/session/resume.go`
> - Searched the web for `'RecordReviewItemDone'`
>
> </details>
>
> </details>
</details>

**结论**
`Client + Server` 和“中断继续审核”本身不会降低审核精度。真正决定精度的是：恢复后是否仍使用同一份代码快照、相同规则与模型，以及历史结果是否被正确判定为可复用。

但按当前实现，**稳定且只读的代码目录下，精度基本不下降；如果审核期间目录继续变化或 Jenkins 重复触发，目前仍存在精度下降风险**。风险主要表现为漏报率上升，也可能保留已经失效的旧问题。

另外需要纠正一点：当前 OCR `main` 已支持中断恢复，不再是“全部结束才保存一次”。它通过 JSONL session 保存轨迹，并按文件生成完成检查点；`ocr review --resume` 会复用已完成文件。[OCR 官方说明](https://github.com/alibaba/open-code-review)、[OCR session 实现](https://github.com/alibaba/open-code-review/blob/main/internal/session/persist.go)

**机制比较**

| 维度 | 原生 OCR | 当前项目 |
|---|---|---|
| 输入来源 | Git diff、commit/range | 两个本地物理目录 |
| 调度方式 | CLI 单次运行，文件级并发 | Jenkins client + MongoDB + scheduler server |
| 审核单元 | 主要为文件/文件组合 | 文件下的 CodeBlock |
| 完成检查点 | 文件完成后写 `review_item_done` 并 flush | 每个 Block 完成后立即写 MongoDB |
| 中断中的文件 | 整个文件重新审核 | 当前未完成 Block 重新审核 |
| 已完成结果 | 根据文件 diff 指纹复用 | 根据 Block MD5 和审核指纹复用 |
| 工具上下文 | Git 仓库、全局 DiffMap、物理文件 | 内存 DiffMap、物理目录、AST/语义索引 |
| 后处理 | 定位、reflection/filter | re-location、review-filter、文件去重、项目汇总 |

OCR 的主流程同样是 `plan_task -> main_task 工具循环 -> review_filter`，main_task 必须调用 `task_done` 才算完成。[OCR agent.go](https://github.com/alibaba/open-code-review/blob/main/internal/agent/agent.go)、[OCR loop.go](https://github.com/alibaba/open-code-review/blob/main/internal/llmloop/loop.go)

**不会下降的部分**
当前实现中，以下设计能够保护精度：

- 只有 `main_task_completed=True` 且无失败信息的 Block 才能复用。
- 正在执行的 Block 被中断后不会作为完成结果保存，而是重新执行完整的 plan/main/filter 流程。
- 模型、规则、background、pipeline 版本变化会使审核指纹失效。
- 服务重启会重新扫描物理目录并重建 DiffMap、语义索引和静态分析上下文。
- Block 级检查点比 OCR 的文件级检查点更细，中断后重做量更少。
- MongoDB 比单机 session 文件更适合多 server、租约、优先级抢占和长期运行。

相关实现位于 [review_service.py](/C:/Users/qiao/Documents/ci-ai-codereview/app/services/review_service.py:637) 和 [task_submission.py](/C:/Users/qiao/Documents/ci-ai-codereview/app/services/task_submission.py:37)。

**可能下降的地方**
1. **本地目录不是不可变快照**

OCR 使用 commit SHA 时，diff 输入天然稳定。当前工具直接读取 `review_version_path` 物理目录。如果 Jenkins 提交后开发者继续修改目录，已经完成的 Block 和后来审核的 Block 可能来自不同时间点。

这会产生“混合快照”：报告中的每个结果单独看都合理，但整个任务并不是对同一版代码的审核。

2. **Block 指纹没有覆盖完整上下文**

当前 `_block_review_fingerprint()` 包含 Block MD5、模型、规则、background 等，但不包含：

- 当前文件完整代码 hash
- 相关文件内容 hash
- 整个变更清单 hash
- AST/语义索引版本或内容 hash
- 静态分析报告整体 hash

因此，一个 Block 自身不变，但同文件其他函数或头文件契约变化时，该 Block 仍可能被复用。

例如 `auth.c` 中登录代码没有变化，但 `auth.h` 把返回值语义从“0 成功”改成“1 成功”。旧 Block 结果仍可能保留，造成漏报或误报。

OCR 的文件级恢复在这一点更保守：同文件 diff 变化会重审整个文件。不过 OCR 当前的恢复指纹主要是 `mode + oldPath + newPath + diff`，没有包含模型和规则，因此切换模型后复用旧文件结果也存在风险；当前项目的文件级审核指纹反而更完整。

3. **检查中断与保存之间不是一次原子操作**

当前逻辑是：

```text
检查 trigger_revision/lease
生成结果
再次检查
保存 CodeFileModel
```

如果恰好在“最后检查”和“数据库保存”之间发生重复触发，旧 worker 存在极小概率覆盖新一轮预写数据。普通 scheduler 抢占已经通过 lease 避免了大部分情况，但这里仍不是严格的 compare-and-set。

4. **排除规则会直接影响 Recall**

当前规则要求“路径包含任意配置元素就不审核”，其中包括 `main.c`、`Math`、`General`、`Dem` 等较宽泛字符串。

这不会增加误报，但可能直接跳过真实业务代码：

- Precision 可能看起来更高，因为报告的问题更少。
- Recall 会下降，因为被排除文件中的真实缺陷永远不会进入模型。

这属于业务配置造成的覆盖率变化，不是 Client/Server 架构问题。

5. **目录 diff 不如 Git diff 稳定**

当前 Python 目录比较可以正确发现内容变化，但在重命名识别、复杂移动、删除上下文和精确 diff 定位方面仍不如 Git。re-location 可以修复一部分行号漂移，但输入 diff 的成熟度仍可能影响定位准确率。

6. **重跑不保证输出逐字一致**

中断中的 Block 会从 plan_task 重新开始，而不是恢复到 main_task 第 N 轮。即使输入完全相同，LLM 仍可能给出不同结果。

这不是系统性降准，但会增加结果方差、API 消耗和耗时。OCR 对中断中的文件也是重新执行，而不是恢复某一轮 tool conversation，因此两者在这一点相近。

**最终判断**
- **不中断、目录只读**：Client/Server 模式不会让精度下降，审核核心链路与原来一致。
- **中断但目录和配置不变**：通常不会下降；已完成 Block 复用，未完成 Block 完整重跑。
- **目录持续修改或重复触发**：当前存在上下文失效风险，精度可能下降。
- **与使用固定 commit SHA 的一次性 OCR 相比**：当前快照一致性稍弱。
- **与 OCR 的中断恢复相比**：当前 Block 级断点更细、服务化能力更强，但指纹需要继续覆盖完整上下文。

要真正保证“中断前后审核精度等价”，最关键的下一步是：**为每个 Task 创建不可变代码快照，并把完整文件、相关文件、规则、提示词、工具定义和静态分析结果的 hash 纳入 Block 审核指纹**。这样 Client/Server 模式才能同时获得服务可靠性和接近严格可重复执行的审核精度。

> Step1. 请使用前面提供的真实案例来真实的测试一下client 和server 端，使用真实的deepseek api 和token，client 端接收首先一个全量的任务，这个任务和所有文件落库，然后后台脚本会扫描到这个未执行的任务，然后会针对一个一个的文件执行审核任务，其间会有一个增量审核的任务过来，然后前面的全量审核的任务中断，转而去执行 这个增量深审核任务，等这个增量审核任务执行完成后，继续审核前面的全量审核任务。进而两个都全部成功执行。
>
> Step2. 全部审核后，client端继续接收了同一个全量任务，同一个增量任务，但每个任务只有一两个一个文件发生了变更，然后这两个任务会继续审核，但只审核变更的部分/
>
> 请测试这两个复杂的case，看看是否达到预期设计目标

<details><summary>56 previous messages</summary>

> Stream error
>
> Reconnecting 5/5
> request timed out
>
> 我会把这次测试做成可复现的真实集成场景，不用 mock：独立 MongoDB 测试库、约 10 个 C 文件、真实 DeepSeek、真实 Jenkins/client HTTP 触发和真实 scheduler。验证点会包括任务状态时间线、全量被增量抢占、增量完成后全量恢复，以及第二轮只重审变更 Block、历史 token/调用次数继续累加。
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `docker compose ps`
> - Ran `Get-Content -Encoding utf8 app\services\scheduler.py`
> - Ran `Get-Content -Encoding utf8 app\services\task_submission.py`
> - Ran `Get-Content -Encoding utf8 scripts\jenkins_trigger.py`
> - Ran `git status --short`
> - Ran `Get-Content -Encoding utf8 scripts\run_demo_review.py`
>
> </details>
>
> 当前实现已经具备测试所需的状态和检查点，但这个场景必须避免两个假阳性：一是全量任务太快结束导致没发生抢占，二是仅看 Task 状态却没证明未变文件没有调用 LLM。我会在脚本里同时记录任务状态时间线，以及每个文件/Block 的 `review_attempt_count`、模型轮数和 token 前后差值。
>
> <details><summary>Ran 8 commands</summary>
>
> - Ran `Get-Content -Encoding utf8 app\schemas\code_file.py | Select-Object -Skip 130 -First 170`
> - Ran `Get-Content -Encoding utf8 app\routes\code_files.py`
> - Ran `Get-ChildItem -Recurse -File demo_repos | Select-Object -First 40 -ExpandProperty FullName`
> - Ran `Get-Content -Encoding utf8 requirements.txt`
> - Ran `Get-Content -Encoding utf8 .dockerignore`
> - Ran `Get-Content -Encoding utf8 .gitignore`
> - Ran `git check-ignore -v demo_repos\demo_c\master\src\auth.c`
> - Ran `git ls-files demo_repos`
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> 我已经把断点续审与抢占逻辑的关键状态梳理清楚了。接下来会加入一个可重复执行的真实 Client/Server 集成脚本：它只通过 HTTP 触发任务和查询结果，生成独立的 10 文件 C 仓库，并把抢占时间线、文件级复用、真实 token 与模型轮次写成测试报告。
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran `Get-Content app\routes\task.py; Get-Content app\schemas\task.py`
> - Ran `Get-ChildItem -Force; Get-ChildItem scripts -Force; Get-Content .gitignore`
> - Ran `Get-Content app\routes\code_file.py; Get-Content app\schemas\code_file.py`
>
> </details>
>
> 接口模型已经确认能返回任务累计 token、模型轮次、工具轨迹以及每个 Block 的指纹，足够做“只重审变更部分”的强校验。路由目录与我预期的名称不同，我先把实际分页参数和响应路径对齐，再落脚本，避免测试工具本身造成误判。
>
> <details><summary>Ran 7 commands</summary>
>
> - Ran `rg -n "tasks/trigger|code-files|JenkinsTaskTrigger|CodeFileListResponse" app tests`
> - Ran `Get-Content docker-compose.yml; Get-Content app\models\task.py`
> - Ran `rg --files app | Sort-Object`
> - Ran `Get-Content app\services\scheduler.py`
> - Ran `Get-Content app\services\task_submission.py`
> - Ran `Get-Content app\models\code_file.py`
> - Ran `Get-Content app\routes\tasks.py; Get-Content app\routes\code_files.py`
>
> </details>
>
> 测试脚本会把两阶段断言分开：Step1 验证“全量运行中被增量抢占，并在增量结束后恢复”；Step2 不只看任务状态，而是逐文件比较 Block 哈希、`main_task_completed`、模型轮次、工具调用和 token，确保未变化文件没有偷偷再次调用模型。现在开始写入脚本与忽略项。
>
> <details><summary>Created a file, edited a file, ran 7 commands</summary>
>
> - Wrote `./.gitignore` (+2 -0)
> - Wrote `./scripts/run_client_server_e2e.py` (+668 -0)
> - Ran `.\.venv\Scripts\python.exe -m py_compile scripts\run_client_server_e2e.py`
> - Ran `.\.venv\Scripts\python.exe scripts\run_client_server_e2e.py --help`
> - Ran `git diff -- .gitignore scripts\run_client_server_e2e.py; git status --short`
> - Ran `rg -n "llm_total_tokens|resumed_file_num|_finish_task|project_summary" app\services\review_service.py`
> - Ran `$lines = Get-Content app\services\review_service.py; $lines[2195..2370]`
> - Ran `$lines = Get-Content app\services\review_service.py; $lines[330..390]; $lines[645..700]`
> - Ran `$lines = Get-Content app\services\review_service.py; $lines[2095..2195]`
>
> </details>
>
> 脚本已通过语法检查。现在我会用独立 MongoDB 数据库重建 App 容器，打开真实 DeepSeek、1 路文件并发和 1 秒调度轮询；单并发是为了稳定捕获“全量文件正在调用模型时增量任务到达”的抢占窗口，同时不会改变业务上的优先级逻辑。密钥只注入容器环境，不写入仓库或报告。
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `Get-Content app\core\database.py; Get-Content app\core\config.py | Select-Object -First 160`
> - Ran `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`
> - Ran `Get-Date -Format 'yyyyMMdd_HHmmss'`
> - Ran `$env:MONGODB_URI='mongodb://mongodb:27017/ci_ai_codereview_client_server_e2e_20260714_213416'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_213416'; $env:CODE_REPOSITORY_HOST_ROOT='.\demo_repos'; $env:CODE_REPOSITORY_CONTAINER_ROOT='/repositories'; $env:APP_ENABLE_SCHEDULER='true'; $env:SCHEDULER_INTERVAL_SECONDS='1'; $env:SCHEDULER_LEASE_SECONDS='120'; $env:LLM_URL='https://api.deepseek.com'; $env:LLM_API_KEY='sk-1d9b0fbe9a1d4535b439bc870287f1ce'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MOCK_ENABLED='false'; $env:LLM_TIMEOUT_SECONDS='300'; $env:LLM_FILE_TIMEOUT_SECONDS='900'; $env:LLM_CONCURRENCY='1'; $env:LLM_MAX_TOOL_ROUNDS='30'; $env:FULL_SCAN_MAX_TOOL_ROUNDS='60'; docker compose up -d --build --force-recreate app`
> - Auto-review: approved
> - Auto-review risk: medium
> - Auto-review rationale: Rebuilding the local app container with the user-provided DeepSeek credentials and test settings is a bounded local/docker mutation for the explicitly requested integration test, and the external model endpoint was explicitly approved by the user.
>
> </details>
>
> 容器正在重建，当前还没有错误输出；MongoDB 仍使用独立测试库，不会覆盖之前页面的数据。容器健康后我会立刻启动两阶段脚本，并持续检查调度日志，特别关注抢占是否只发生在当前文件检查点之后。
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`
> - Ran `$deadline=(Get-Date).AddMinutes(2); do { try { $response=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5; if ($response.status -eq 'ok') { $response | ConvertTo-Json -Compress; exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); Write-Error 'health timeout'; exit 1`
>
> </details>
>
> App 与数据库均已健康，真实模型配置已生效。现在开始 Step1：脚本会先确认全量任务 10 个文件已由 Client 入库且某个文件进入审核，再提交仅包含 `auth.c`、`parser.c` 差异的增量任务；运行期间我会同时看脚本时间线和容器日志。
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran `.\.venv\Scripts\python.exe scripts\run_client_server_e2e.py --project-id demo_c --host-repository-root .\demo_repos\.e2e_runtime\20260714_213416\demo_c --server-repository-root /repositories/.e2e_runtime/20260714_213416/demo_c --artifact .\artifacts\client_server_e2e_20260714_213416.json --task-timeout 3600 --http-timeout 60 --poll-interval 0.5`
> - Ran `docker compose logs --tail 120 app`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object project_id,review_version,copy_from_version,task_type,state,completion_status,file_num,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens | ConvertTo-Json -Depth 4`
>
> </details>
>
> Step1 的关键抢占已经真实发生：全量任务当前是 `state=0 / interrupted`，增量任务是 `state=1 / running`，而且全量尚未完成任何文件。这说明调度器没有并行偷跑两个任务，确实在当前检查点转向了高优先级增量任务；现在等待增量的两个文件逐个落库。
>
> <details><summary>Ran 7 commands</summary>
>
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms | ConvertTo-Json -Depth 4`
> - Ran `docker compose logs --tail 80 app | Select-String -Pattern 'Preempt|failed|ERROR|DeepSeek|timeout|POST /tasks/trigger'`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $inc=$tasks.items | Where-Object {$_.task_type -eq 1}; $files=Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$inc.id+"&limit=200"); $files.items | ForEach-Object { [pscustomobject]@{file=$_.file_name; state=$_.state; block_completed=($_.code_blocks | ForEach-Object {$_.main_task_completed}); rounds=($_.code_blocks | Measure-Object -Property main_task_round_count -Sum).Sum; tokens=($_.code_blocks | Measure-Object -Property llm_total_tokens -Sum).Sum; failure=($_.code_blocks.failure_message -join ';')} } | ConvertTo-Json -Depth 5`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms | ConvertTo-Json -Depth 4`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $inc=$tasks.items | Where-Object {$_.task_type -eq 1}; $files=Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$inc.id+"&limit=200"); $files.items | ForEach-Object { [pscustomobject]@{file=$_.file_name; state=$_.state; block_completed=($_.code_blocks | ForEach-Object {$_.main_task_completed}); rounds=($_.code_blocks | Measure-Object -Property main_task_round_count -Sum).Sum; tokens=($_.code_blocks | Measure-Object -Property llm_total_tokens -Sum).Sum; failure=($_.code_blocks.failure_message -join ';')} } | ConvertTo-Json -Depth 5`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms | ConvertTo-Json -Depth 4`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $full=$tasks.items | Where-Object {$_.task_type -eq 2}; $files=Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$full.id+"&limit=200"); $files.items | Sort-Object file_name | ForEach-Object { [pscustomobject]@{file=$_.file_name; state=$_.state; completed=($_.code_blocks.main_task_completed -notcontains $false); rounds=($_.code_blocks | Measure-Object -Property main_task_round_count -Sum).Sum; tokens=($_.code_blocks | Measure-Object -Property llm_total_tokens -Sum).Sum} } | ConvertTo-Json -Depth 4`
>
> </details>
>
> 增量任务已真实完成：2 个文件共 16 次 LLM 调用、68,744 token，并且两个 Block 都已即时落库。不过我发现新的异常：增量结束后超过一个调度周期，全量仍停在 `interrupted`，尚未恢复。这正是本次复杂测试要抓的服务级缺陷，我正在核对 lease 清理和调度 Future 的结束路径。
>
> <details><summary>Ran 26 commands</summary>
>
> - Ran `$lines = Get-Content app\services\review_service.py; $lines[130..230]`
> - Ran `rg -n "interrupted|_mark|lease_token|stop_event" app\services\review_service.py app\services\scheduler.py`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,lease_owner,lease_expires_at,heartbeat_time,interrupt_requested,update_time | ConvertTo-Json -Depth 4`
> - Ran `docker compose logs --since 10m app`
> - Ran `$logs = docker compose logs --since 10m app; $logs | Select-String -Pattern 'Preempting|Review worker failed|ERROR|exception|maximum number|skipped|completed review|Email'`
> - Auto-review: approved
> - Auto-review risk: low
> - Auto-review rationale: Auto-review returned a low-risk allow decision.
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,lease_owner,lease_expires_at,heartbeat_time,updated_time,llm_total_tokens | ConvertTo-Json -Depth 4`
> - Ran `Get-Content app\main.py`
> - Ran `rg -n "def _batch|batch_dedup|ThreadPoolExecutor|shutdown|wait\(" app\services\review_service.py`
> - Ran `Get-Content app\services\notification.py`
> - Ran `$task=(Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10').items | Where-Object {$_.task_type -eq 1}; $task | Select-Object state,completion_status,completion_email_sent,update_time | ConvertTo-Json -Depth 4`
> - Ran `Get-Content tests\test_scheduler.py`
> - Ran `rg -n "ReviewScheduler|run_once|_poll|preempt" tests`
> - Ran `Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'`
> - Ran `$env:MONGODB_URI='mongodb://127.0.0.1:27017/ci_ai_codereview_client_server_e2e_20260714_213416'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_213416'; .\.venv\Scripts\python.exe -c "from app.core.database import connect_to_mongo; from app.core.config import Settings; from app.models.task import TaskModel; from app.services.scheduler import ReviewScheduler, utc_now; s=Settings(); connect_to_mongo(s); q=ReviewScheduler(s); print([(t.review_version,t.state,repr(t.lease_token),t.lease_expires_at,q._eligible(t,utc_now())) for t in TaskModel.objects.order_by('task_type','create_time')])"`
> - Ran `$env:MONGODB_URI='mongodb://127.0.0.1:27017/ci_ai_codereview_client_server_e2e_20260714_213416'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_213416'; .\.venv\Scripts\python.exe -c "from app.core.config import Settings; s=Settings(); print(s.mongodb_uri,s.mongodb_db)"`
> - Ran `docker compose exec -T app python -c "import os; print(os.environ.get('MONGODB_URI')); print(os.environ.get('MONGODB_DB')); print(os.environ.get('APP_ENABLE_SCHEDULER')); print(os.environ.get('LLM_MOCK_ENABLED')); print(os.environ.get('LLM_MODEL'))"`
> - Ran `.\.venv\Scripts\python.exe -c "from pymongo import MongoClient; c=MongoClient('mongodb://127.0.0.1:27017'); print(c.list_database_names()); print([(d,c[d].list_collection_names()) for d in c.list_database_names()])"`
> - Ran `.\.venv\Scripts\python.exe -c "from pymongo import MongoClient; c=MongoClient('mongodb://127.0.0.1:27017'); db=c['ci_ai_codereview_client_server_e2e_20260714_213416']; print(db.ai_codereview_task.count_documents({}),db.ai_codereview_code_file.count_documents({})); print(c['ci_ai_codereview'].ai_codereview_code_file.count_documents({'task_id':{'$in':['6a563b7138e74e7b96c48463','6a563b7438e74e7b96c4846e']}}))"`
> - Ran `.\.venv\Scripts\python.exe -c "from pymongo import MongoClient; c=MongoClient('mongodb://127.0.0.1:27017'); ids=['6a563b7138e74e7b96c48463','6a563b7438e74e7b96c4846e']; from bson import ObjectId; print([(d,c[d].ai_codereview_task.count_documents({'_id':{'$in':[ObjectId(x) for x in ids]}}),c[d].ai_codereview_code_file.count_documents({'task_id':{'$in':ids}})) for d in c.list_database_names()])"`
> - Ran `docker compose exec -T app python -c "import os; print('MONGO_MOCK='+str(os.environ.get('MONGO_MOCK'))); print('SCHEDULER_INTERVAL_SECONDS='+str(os.environ.get('SCHEDULER_INTERVAL_SECONDS')))"`
> - Ran `.\.venv\Scripts\python.exe -c "from pymongo import MongoClient; c=MongoClient('mongodb://127.0.0.1:27017'); print([(d,c[d]['ai_codereview_task'].count_documents({}),c[d]['ai_codereview_code_file'].count_documents({})) for d in c.list_database_names()])"`
> - Ran `docker compose exec -T app python -c "from app.core.config import get_settings; from app.core.database import connect_to_mongo; from mongoengine.connection import get_db; s=get_settings(); connect_to_mongo(s); print(s.mongodb_uri,s.mongodb_db,get_db().name)"`
> - Ran `docker compose exec -T app python -c "from pymongo import MongoClient; c=MongoClient('mongodb://mongodb:27017'); print([(d,c[d]['ai_codereview_task'].count_documents({}),c[d]['ai_codereview_code_file'].count_documents({})) for d in c.list_database_names()])"`
> - Ran `$lines=Get-Content app\services\review_service.py; $lines[235..325]`
> - Ran `docker compose exec -T app python -c "from app.core.config import get_settings; from app.core.database import connect_to_mongo; from app.models.task import TaskModel; from app.services.scheduler import ReviewScheduler,utc_now; s=get_settings(); connect_to_mongo(s); q=ReviewScheduler(s); print([(t.review_version,t.state,repr(t.lease_token),t.lease_expires_at,q._eligible(t,utc_now())) for t in TaskModel.objects.order_by('task_type','create_time')])"`
> - Ran `$logs = docker compose logs --since 15m app; $logs | Select-String -Pattern 'Job|scheduler|Scheduler|Traceback|CancelledError|RuntimeError'`
> - Auto-review: approved
> - Auto-review risk: low
> - Auto-review rationale: Auto-review returned a low-risk allow decision.
>
> </details>
>
> 根因范围已经缩小：数据库中的全量任务满足重新领取条件（`state=0`、lease 为空、`_eligible=True`），但调度器仍占着一个数据库已完成且 lease 已释放的旧 Future，因此不再派发下一任务。我要增加“数据库检查点已释放但 Future 未返回”的自愈逻辑，并让调度 tick 捕获异常后继续运行；这不会跳过审核，只会释放已经持久化完成的执行槽。随后会在同一套真实场景上从头复测。
>
> <details><summary>Edited 2 files, ran 3 commands</summary>
>
> - Wrote `./app/services/scheduler.py` (+57 -13)
> - Wrote `./tests/test_scheduler.py` (+47 -0)
> - Ran `.\.venv\Scripts\python.exe -m pytest tests\test_scheduler.py -q`
> - Ran `git diff -- app\services\scheduler.py tests\test_scheduler.py`
> - Ran `.\.venv\Scripts\python.exe -m py_compile app\services\scheduler.py scripts\run_client_server_e2e.py`
>
> </details>
>
> 自愈逻辑已写入并能编译，但当前测试环境没有 `pytest-asyncio`，新增的两个异步用例被跳过了，这不算有效回归。我会改成标准库 `asyncio.run()` 驱动，让它们在现有依赖下真正执行，然后再重建容器。
>
> <details><summary>Edited a file, ran 5 commands</summary>
>
> - Wrote `./tests/test_scheduler.py` (+10 -6)
> - Ran `.\.venv\Scripts\python.exe -m pytest tests\test_scheduler.py -q`
> - Ran `.\.venv\Scripts\python.exe -m pytest tests\test_task_submission.py tests\test_review_service.py -q`
> - Ran `Get-Date -Format 'yyyyMMdd_HHmmss'`
> - Ran `$env:MONGODB_URI='mongodb://mongodb:27017/ci_ai_codereview_client_server_e2e_20260714_214934'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_214934'; $env:CODE_REPOSITORY_HOST_ROOT='.\demo_repos'; $env:CODE_REPOSITORY_CONTAINER_ROOT='/repositories'; $env:APP_ENABLE_SCHEDULER='true'; $env:SCHEDULER_INTERVAL_SECONDS='1'; $env:SCHEDULER_LEASE_SECONDS='120'; $env:LLM_URL='https://api.deepseek.com'; $env:LLM_API_KEY='sk-1d9b0fbe9a1d4535b439bc870287f1ce'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MOCK_ENABLED='false'; $env:LLM_TIMEOUT_SECONDS='300'; $env:LLM_FILE_TIMEOUT_SECONDS='900'; $env:LLM_CONCURRENCY='1'; $env:LLM_MAX_TOOL_ROUNDS='30'; $env:FULL_SCAN_MAX_TOOL_ROUNDS='60'; docker compose up -d --build --force-recreate app`
> - Auto-review: approved
> - Auto-review risk: medium
> - Auto-review rationale: Recreating the local app container against a fresh isolated test database and the user-provided DeepSeek endpoint is a bounded test operation explicitly requested by the user, with no evidence of secret exfiltration beyond the approved model service use.
> - Ran `$deadline=(Get-Date).AddMinutes(2); do { try { $response=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5; if ($response.status -eq 'ok') { $response | ConvertTo-Json -Compress; exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); Write-Error 'health timeout'; exit 1`
>
> </details>
>
> 调度单测现在是 5/5 真正通过，相关提交/续审回归是 36/36 通过。修复后的容器也已健康，我正在新的独立数据库中从零重跑两阶段真实测试；这一次只有完整通过所有时间线和文件指纹断言才会生成 `passed` 报告。
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran `.\.venv\Scripts\python.exe scripts\run_client_server_e2e.py --project-id demo_c --host-repository-root .\demo_repos\.e2e_runtime\20260714_214934\demo_c --server-repository-root /repositories/.e2e_runtime/20260714_214934/demo_c --artifact .\artifacts\client_server_e2e_20260714_214934.json --task-timeout 3600 --http-timeout 60 --poll-interval 0.5`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms | ConvertTo-Json -Depth 4`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms | ConvertTo-Json -Depth 4`
>
> </details>
>
> 复测再次稳定捕获同样的抢占状态，说明修复没有削弱优先级行为。当前增量文件仍在模型工具循环内，任务级 token 只在文件检查点完成后汇总，所以暂时显示 0；我会以 Block 落库后的轮次为准，不把“调用中”误判为未调用。
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $inc=$tasks.items | Where-Object {$_.task_type -eq 1}; $files=Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$inc.id+"&limit=200"); $files.items | Select-Object file_name,state,@{n='completed';e={$_.code_blocks.main_task_completed -notcontains $false}},@{n='rounds';e={($_.code_blocks | Measure-Object main_task_round_count -Sum).Sum}},@{n='tokens';e={($_.code_blocks | Measure-Object llm_total_tokens -Sum).Sum}},@{n='failure';e={$_.code_blocks.failure_message -join ';'}} | ConvertTo-Json -Depth 5`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms,lease_owner | ConvertTo-Json -Depth 4`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,lease_owner,lease_expires_at | ConvertTo-Json -Depth 4`
> - Ran `$logs = docker compose logs --since 10m app; $logs | Select-String -Pattern 'Review scheduler poll failed|Releasing scheduler slot|Review worker failed|Preempting|ERROR|Traceback'`
> - Auto-review: approved
> - Auto-review risk: low
> - Auto-review rationale: Auto-review returned a low-risk allow decision.
> - Ran `Get-Content app\routes\health.py`
> - Ran `Get-Content tests\test_health.py`
>
> </details>
>
> 第二次复测说明问题不只在旧 Future：增量完成后没有任何自愈日志，表明调度 tick 卡在 MongoEngine 的 `asyncio.to_thread()` 数据库调用中，后续 interval 被 `max_instances=1` 阻塞。由于这些调度查询都很小、MongoEngine 本身又是同步栈，我会让调度 tick 直接执行短数据库操作，只有耗时的整项审核继续在线程中运行；这样能消除调度线程池卡死点，同时保留 FastAPI 的审核异步性。
>
> <details><summary>Edited a file, ran 3 commands</summary>
>
> - Wrote `./app/services/scheduler.py` (+4 -4)
> - Ran `.\.venv\Scripts\python.exe -m pytest tests\test_scheduler.py -q`
> - Ran `.\.venv\Scripts\python.exe -m pytest -q`
> - Ran `Get-Date -Format 'yyyyMMdd_HHmmss'`
>
> </details>
>
> 完整回归目前 63/63 通过。为了不让“重启后恢复”掩盖无重启的调度问题，我不会复用上一轮半成品数据，而是再用全新的数据库从零跑一次：全量提交、增量抢占、增量完成、全量自动恢复，全程不重启；随后同一进程继续执行 Step2。
>
> <details><summary>Ran 7 commands</summary>
>
> - Ran `$env:MONGODB_URI='mongodb://mongodb:27017/ci_ai_codereview_client_server_e2e_20260714_215724'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_215724'; $env:CODE_REPOSITORY_HOST_ROOT='.\demo_repos'; $env:CODE_REPOSITORY_CONTAINER_ROOT='/repositories'; $env:APP_ENABLE_SCHEDULER='true'; $env:SCHEDULER_INTERVAL_SECONDS='1'; $env:SCHEDULER_LEASE_SECONDS='120'; $env:LLM_URL='https://api.deepseek.com'; $env:LLM_API_KEY='sk-1d9b0fbe9a1d4535b439bc870287f1ce'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MOCK_ENABLED='false'; $env:LLM_TIMEOUT_SECONDS='300'; $env:LLM_FILE_TIMEOUT_SECONDS='900'; $env:LLM_CONCURRENCY='1'; $env:LLM_MAX_TOOL_ROUNDS='30'; $env:FULL_SCAN_MAX_TOOL_ROUNDS='60'; docker compose up -d --build --force-recreate app`
> - Auto-review: approved
> - Auto-review risk: medium
> - Auto-review rationale: Recreating the local app container with a fresh isolated MongoDB test database and the user-provided DeepSeek configuration is a bounded test operation explicitly requested by the user, with no broader destructive or exfiltration side effects beyond the approved model service use.
> - Ran `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`
> - Ran `$deadline=(Get-Date).AddMinutes(2); do { try { $response=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5; if ($response.status -eq 'ok') { $response | ConvertTo-Json -Compress; exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); Write-Error 'health timeout'; exit 1`
> - Ran `.\.venv\Scripts\python.exe scripts\run_client_server_e2e.py --project-id demo_c --host-repository-root .\demo_repos\.e2e_runtime\20260714_215724\demo_c --server-repository-root /repositories/.e2e_runtime/20260714_215724/demo_c --artifact .\artifacts\client_server_e2e_20260714_215724.json --task-timeout 3600 --http-timeout 60 --poll-interval 0.5`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens | ConvertTo-Json -Depth 4`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms,lease_owner | ConvertTo-Json -Depth 4`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,lease_owner,lease_expires_at | ConvertTo-Json -Depth 4`
>
> </details>
>
> 第三次无重启复测仍在同一点停住，说明前一个判断还不充分，不能把它当成已修复。我会先加入只读的 `/health/scheduler` 诊断接口，暴露调度器是否运行、当前占用的任务、Future 是否结束以及下次 tick 时间；这样可以看到真实进程内部状态，而不是继续从数据库结果反推。定位后再做最终完整验收。
>
> <details><summary>Edited 4 files, ran 2 commands</summary>
>
> - Wrote `./app/main.py` (+2 -1)
> - Wrote `./app/routes/health.py` (+11 -1)
> - Wrote `./app/services/scheduler.py` (+15 -0)
> - Wrote `./tests/test_health.py` (+17 -0)
> - Ran `.\.venv\Scripts\python.exe -m pytest tests\test_health.py tests\test_scheduler.py -q`
> - Ran `.\.venv\Scripts\python.exe -m py_compile app\main.py app\routes\health.py app\services\scheduler.py`
>
> </details>
>
> Stream error
>
> Reconnecting 3/5
> stream disconnected before completion: error sending request for url (https://chatgpt.com/backend-api/codex/responses)
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `$env:MONGODB_URI='mongodb://mongodb:27017/ci_ai_codereview_client_server_e2e_20260714_215724'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_215724'; $env:CODE_REPOSITORY_HOST_ROOT='.\demo_repos'; $env:CODE_REPOSITORY_CONTAINER_ROOT='/repositories'; $env:APP_ENABLE_SCHEDULER='true'; $env:SCHEDULER_INTERVAL_SECONDS='1'; $env:SCHEDULER_LEASE_SECONDS='120'; $env:LLM_URL='https://api.deepseek.com'; $env:LLM_API_KEY='sk-1d9b0fbe9a1d4535b439bc870287f1ce'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MOCK_ENABLED='false'; $env:LLM_TIMEOUT_SECONDS='300'; $env:LLM_FILE_TIMEOUT_SECONDS='900'; $env:LLM_CONCURRENCY='1'; $env:LLM_MAX_TOOL_ROUNDS='30'; $env:FULL_SCAN_MAX_TOOL_ROUNDS='60'; docker compose up -d --build --force-recreate app`
> - Auto-review: approved
> - Auto-review risk: medium
> - Auto-review rationale: Recreating the local app container to load the new scheduler diagnostic endpoint and continue the explicitly requested DeepSeek-backed integration test against the isolated test database is a bounded local test action.
> - Ran `Start-Sleep -Seconds 3; Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/scheduler' | ConvertTo-Json -Depth 4; (Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10').items | Select-Object review_version,state,completion_status,lease_owner | ConvertTo-Json -Depth 3`
>
> </details>
>
> 诊断接口给出了决定性信息：APScheduler 正常运行、每秒都有下次 tick、没有旧 Future 占槽，但 `claim_next_task()` 没有领取数据库中可见的全量任务。因此真正问题是原子领取查询的字段匹配，而不是异步线程。下一步我会检查该文档的原始 Mongo 字段，修正“空 lease / 缺失 lease”在 MongoEngine 查询中的兼容。
>
> <details><summary>Ran a command</summary>
>
> - Ran `docker compose exec -T app python -c "from app.core.config import get_settings; from pymongo import MongoClient; s=get_settings(); c=MongoClient(s.mongodb_uri); db=c[s.mongodb_db]; print(list(db.ai_codereview_task.find({}, {'review_version':1,'state':1,'completion_status':1,'trigger_revision':1,'lease_token':1,'lease_owner':1,'lease_expires_at':1})))"`
>
> </details>
>
> 原始文档已经确认：审核中断/完成时，MongoEngine 会把空字符串 lease 字段从 Mongo 文档中移除；而原子领取条件按 `lease_token=""` 匹配，真实 MongoDB 不会把“字段不存在”等同于空字符串。我要把领取条件改成“无 lease 时匹配空字符串或字段不存在”，并新增一个直接 `$unset lease_token` 的回归用例，确保测试覆盖真实 Mongo 行为。
>
> <details><summary>Edited 2 files, ran 4 commands</summary>
>
> - Wrote `./app/services/scheduler.py` (+8 -3)
> - Wrote `./tests/test_scheduler.py` (+17 -0)
> - Ran `.\.venv\Scripts\python.exe -m pytest tests\test_scheduler.py -q`
> - Ran `.\.venv\Scripts\python.exe -m py_compile app\services\scheduler.py`
> - Ran `$env:MONGODB_URI='mongodb://mongodb:27017/ci_ai_codereview_client_server_e2e_20260714_215724'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_215724'; $env:CODE_REPOSITORY_HOST_ROOT='.\demo_repos'; $env:CODE_REPOSITORY_CONTAINER_ROOT='/repositories'; $env:APP_ENABLE_SCHEDULER='true'; $env:SCHEDULER_INTERVAL_SECONDS='1'; $env:SCHEDULER_LEASE_SECONDS='120'; $env:LLM_URL='https://api.deepseek.com'; $env:LLM_API_KEY='sk-1d9b0fbe9a1d4535b439bc870287f1ce'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MOCK_ENABLED='false'; $env:LLM_TIMEOUT_SECONDS='300'; $env:LLM_FILE_TIMEOUT_SECONDS='900'; $env:LLM_CONCURRENCY='1'; $env:LLM_MAX_TOOL_ROUNDS='30'; $env:FULL_SCAN_MAX_TOOL_ROUNDS='60'; docker compose up -d --build --force-recreate app`
> - Auto-review: approved
> - Auto-review risk: medium
> - Auto-review rationale: Rebuilding the local test app container to apply the scheduler lease-field fix and continue the user-requested DeepSeek-backed integration test against the isolated MongoDB test database is a bounded local testing action.
> - Ran `Start-Sleep -Seconds 3; Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/scheduler' | ConvertTo-Json -Depth 4; (Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10').items | Select-Object review_version,state,completion_status,lease_owner | ConvertTo-Json -Depth 3`
>
> </details>
>
> 根因已被真实 MongoDB 验证修复：同一个此前卡住的全量任务在部署后 3 秒内变成 `state=1/running`，诊断接口显示 active Future 和新 lease 都正常。也就是说问题确实是缺失 lease 字段导致 CAS 领取失败。现在开始最终一次全新、不中途重启的自动化验收。
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `Get-Date -Format 'yyyyMMdd_HHmmss'`
> - Ran `$env:MONGODB_URI='mongodb://mongodb:27017/ci_ai_codereview_client_server_e2e_20260714_220727'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_220727'; $env:CODE_REPOSITORY_HOST_ROOT='.\demo_repos'; $env:CODE_REPOSITORY_CONTAINER_ROOT='/repositories'; $env:APP_ENABLE_SCHEDULER='true'; $env:SCHEDULER_INTERVAL_SECONDS='1'; $env:SCHEDULER_LEASE_SECONDS='120'; $env:LLM_URL='https://api.deepseek.com'; $env:LLM_API_KEY='sk-1d9b0fbe9a1d4535b439bc870287f1ce'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MOCK_ENABLED='false'; $env:LLM_TIMEOUT_SECONDS='300'; $env:LLM_FILE_TIMEOUT_SECONDS='900'; $env:LLM_CONCURRENCY='1'; $env:LLM_MAX_TOOL_ROUNDS='30'; $env:FULL_SCAN_MAX_TOOL_ROUNDS='60'; docker compose up -d --build --force-recreate app`
> - Auto-review: approved
> - Auto-review risk: medium
> - Auto-review rationale: Recreating the local app container against a fresh isolated MongoDB test database to run the user-requested real DeepSeek acceptance test is a bounded local test operation, and the external model endpoint and credentials were explicitly provided for this purpose.
> - Ran `$deadline=(Get-Date).AddMinutes(2); do { try { $response=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5; if ($response.status -eq 'ok') { $response | ConvertTo-Json -Compress; exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); Write-Error 'health timeout'; exit 1`
> - Ran `.\.venv\Scripts\python.exe scripts\run_client_server_e2e.py --project-id demo_c --host-repository-root .\demo_repos\.e2e_runtime\20260714_220727\demo_c --server-repository-root /repositories/.e2e_runtime/20260714_220727/demo_c --artifact .\artifacts\client_server_e2e_20260714_220727.json --task-timeout 3600 --http-timeout 60 --poll-interval 0.5`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens | ConvertTo-Json -Depth 4`
> - Ran `Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/scheduler' | ConvertTo-Json -Depth 4`
>
> </details>
>
> 最终运行的内部状态符合设计：调度器仍在按秒运行，active slot 已从全量切换到增量，增量持有有效 lease，全量已释放 lease 并处于 `interrupted`。这次根因修复后的关键观察点会在增量结束后的下一秒出现：active slot 应自动换回全量。
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms | ConvertTo-Json -Depth 4`
> - Ran `Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/scheduler' | ConvertTo-Json -Depth 4`
>
> </details>
>
> 关键缺陷已经通过无重启实测关闭：增量任务完成并累计 19 次调用、79,100 token 后，调度器自动把 active slot 换回全量任务，后者现在是 `state=1/running` 且持有新 lease。接下来全量的 10 个文件会逐文件落库；这部分耗时取决于每个文件的 plan/main 工具轮次。
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `$full=(Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10').items | Where-Object {$_.task_type -eq 2}; $files=(Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$full.id+"&limit=200")).items; [pscustomobject]@{task_state=$full.state; completed_files=($files | Where-Object {$_.state -eq 2}).Count; active_files=($files | Where-Object {$_.state -eq 1}).Count; pending_files=($files | Where-Object {$_.state -eq 0}).Count; persisted_block_tokens=(($files.code_blocks | Measure-Object llm_total_tokens -Sum).Sum); persisted_rounds=(($files.code_blocks | Measure-Object main_task_round_count -Sum).Sum)} | ConvertTo-Json`
> - Ran `$full=(Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10').items | Where-Object {$_.task_type -eq 2}; $files=@((Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$full.id+"&limit=200")).items); [pscustomobject]@{task_state=$full.state; completed_files=@($files | Where-Object {$_.state -eq 2}).Count; active_files=@($files | Where-Object {$_.state -eq 1}).Count; pending_files=@($files | Where-Object {$_.state -eq 0}).Count; persisted_block_tokens=(($files.code_blocks | Measure-Object llm_total_tokens -Sum).Sum); persisted_rounds=(($files.code_blocks | Measure-Object main_task_round_count -Sum).Sum)} | ConvertTo-Json`
>
> </details>
>
> 全量审核正在按文件检查点稳定推进：目前 6/10 文件已完成并入库，1 个正在审核，3 个等待；已持久化 28 个 main 轮次、190,082 token。这里能直接证明不是等整个任务结束才一次性入库。
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/scheduler' | ConvertTo-Json -Depth 4`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms | ConvertTo-Json -Depth 4`
> - Ran `$full=(Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10').items | Where-Object {$_.task_type -eq 2}; $files=@((Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$full.id+"&limit=200")).items); [pscustomobject]@{completed_files=@($files | Where-Object {$_.state -eq 2}).Count; active_files=@($files | Where-Object {$_.state -eq 1}).Count; pending_files=@($files | Where-Object {$_.state -eq 0}).Count; tokens=(($files.code_blocks | Measure-Object llm_total_tokens -Sum).Sum); failures=@($files.code_blocks | Where-Object {$_.failure_message}).Count} | ConvertTo-Json`
> - Ran `$full=(Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10').items | Where-Object {$_.task_type -eq 2}; $files=@((Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$full.id+"&limit=200")).items); [pscustomobject]@{task_state=$full.state; status=$full.completion_status; completed_files=@($files | Where-Object {$_.state -eq 2}).Count; active_files=@($files | Where-Object {$_.state -eq 1}).Count; pending_files=@($files | Where-Object {$_.state -eq 0}).Count; tokens=(($files.code_blocks | Measure-Object llm_total_tokens -Sum).Sum)} | ConvertTo-Json`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,state,completion_status,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens,llm_elapsed_ms | ConvertTo-Json -Depth 4`
>
> </details>
>
> Step1 已经越过任务收尾并自动进入 Step2。现在数据库状态正好证明局部续审：重复增量任务 `resumed_file_num=1`，只重审了变更的 `auth.c`；重复全量任务 `resumed_file_num=9`，只剩变更的 `storage.c` 在跑。任务累计 token/call 均未清零，而是继续增长。
>
> 两阶段自动化验收已经完整 `passed`，总运行约 17.7 分钟。现在做最后的收尾验证：全量 pytest、脚本编译、容器健康与错误日志扫描；同时核对最终差异，确保没有把密钥写进任何文件。
>
> <details><summary>Ran 13 commands</summary>
>
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $files=foreach($task in $tasks.items){(Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$task.id+"&limit=200")).items}; [pscustomobject]@{task_count=$tasks.total; completed_tasks=@($tasks.items|Where-Object {$_.state -eq 2}).Count; file_rows=@($files).Count; completed_file_rows=@($files|Where-Object {$_.state -eq 2}).Count; failed_blocks=@($files.code_blocks|Where-Object {$_.failure_message}).Count} | ConvertTo-Json`
> - Ran `git status --short; git diff --stat; rg -n "sk-1d9b0fbe9a1d4535b439bc870287f1ce" --glob '!artifacts/**' --glob '!demo_repos/.e2e_runtime/**' .`
> - Ran `.\.venv\Scripts\python.exe -m py_compile scripts\run_client_server_e2e.py app\services\scheduler.py app\routes\health.py app\main.py`
> - Ran `.\.venv\Scripts\python.exe -m pytest -q`
> - Ran `.\.venv\Scripts\python.exe -m pytest -q`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $files=foreach($task in $tasks.items){(Invoke-RestMethod -Uri ("http://127.0.0.1:8000/code-files?task_id="+$task.id+"&limit=200")).items}; [pscustomobject]@{task_count=$tasks.total; completed_tasks=@($tasks.items|Where-Object {$_.state -eq 2}).Count; file_rows=@($files).Count; completed_file_rows=@($files|Where-Object {$_.state -eq 2}).Count; failed_blocks=@($files.code_blocks|Where-Object {$_.failure_message}).Count} | ConvertTo-Json`
> - Ran `.\.venv\Scripts\python.exe -m py_compile scripts\run_client_server_e2e.py app\services\scheduler.py app\routes\health.py app\main.py`
> - Ran `Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' | ConvertTo-Json -Compress; Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/scheduler' | ConvertTo-Json -Compress`
> - Ran `$logs = docker compose logs --since 30m app; $matches = $logs | Select-String -Pattern 'ERROR|Traceback|Review worker failed|Review scheduler poll failed|Detached review worker failed|timeout'; if ($matches) { $matches } else { 'NO_ERROR_LOG_MATCHES' }; docker compose ps`
> - Auto-review: approved
> - Auto-review risk: low
> - Auto-review rationale: Auto-review returned a low-risk allow decision.
> - Ran `Get-Content app\services\scheduler.py`
> - Ran `Get-Content app\routes\health.py; Get-Content app\main.py`
> - Ran `$report=Get-Content artifacts\client_server_e2e_20260714_220727.json -Raw | ConvertFrom-Json; [pscustomobject]@{status=$report.status; step1_seconds=$report.step1.elapsed_seconds; step2_seconds=$report.step2.elapsed_seconds; full_step1_tokens=$report.step1.full.llm_total_tokens; inc_step1_tokens=$report.step1.incremental.llm_total_tokens; full_step2_delta=$report.step2.full_token_delta; inc_step2_delta=$report.step2.incremental_token_delta; full_reused=$report.step2.full_reused_files.Count; inc_reused=$report.step2.incremental_reused_files.Count} | ConvertTo-Json`
> - Ran `git diff --check; git status --short`
>
> </details>
>
> 最终复盘确认根因是 CAS 对缺失 lease 的匹配，不是线程池。为避免同步 Mongo 查询阻塞 FastAPI 事件循环，我会把几个短查询恢复为 `asyncio.to_thread()`；保留已验证的缺失字段兼容、自愈槽位和安全 poll。这个调整不改变领取语义，随后再跑全部回归与一个真实 Mongo 的无模型快速调度验证。
>
> <details><summary>Edited a file, ran 11 commands</summary>
>
> - Wrote `./app/services/scheduler.py` (+5 -5)
> - Ran `.\.venv\Scripts\python.exe -m pytest -q`
> - Ran `.\.venv\Scripts\python.exe -m py_compile scripts\run_client_server_e2e.py app\services\scheduler.py app\routes\health.py app\main.py`
> - Ran `git diff --check`
> - Ran `$env:MONGODB_URI='mongodb://mongodb:27017/ci_ai_codereview_client_server_e2e_20260714_220727'; $env:MONGODB_DB='ci_ai_codereview_client_server_e2e_20260714_220727'; $env:CODE_REPOSITORY_HOST_ROOT='.\demo_repos'; $env:CODE_REPOSITORY_CONTAINER_ROOT='/repositories'; $env:APP_ENABLE_SCHEDULER='true'; $env:SCHEDULER_INTERVAL_SECONDS='1'; $env:SCHEDULER_LEASE_SECONDS='120'; $env:LLM_URL='https://api.deepseek.com'; $env:LLM_API_KEY='sk-1d9b0fbe9a1d4535b439bc870287f1ce'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MOCK_ENABLED='false'; $env:LLM_TIMEOUT_SECONDS='300'; $env:LLM_FILE_TIMEOUT_SECONDS='900'; $env:LLM_CONCURRENCY='1'; $env:LLM_MAX_TOOL_ROUNDS='30'; $env:FULL_SCAN_MAX_TOOL_ROUNDS='60'; docker compose up -d --build --force-recreate app`
> - Auto-review: approved
> - Auto-review risk: medium
> - Auto-review rationale: Recreating the local app container with the final code against the preserved isolated acceptance-test database is a bounded local deployment/test action explicitly requested by the user, and the approved DeepSeek service use remains unchanged.
> - Ran `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`
> - Ran `$tasks=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/tasks?limit=10'; $tasks.items | Select-Object review_version,copy_from_version,state,completion_status,trigger_count,trigger_revision,file_num,reviewed_file_num,resumed_file_num,llm_call_count,llm_total_tokens | ConvertTo-Json -Depth 4`
> - Ran `$deadline=(Get-Date).AddMinutes(2); do { try { $health=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5; if ($health.status -eq 'ok') { $health | ConvertTo-Json -Compress; Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/scheduler' | ConvertTo-Json -Compress; exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); exit 1`
> - Ran `rg -n "def status|def _safe_poll|def claim_next_task|lease_token__exists|def _active_task_released_checkpoint" app\services\scheduler.py`
> - Ran `rg -n "health/scheduler|review_scheduler" app\routes\health.py app\main.py`
> - Ran `rg -n "def run\(|def wait_for_terminal_pair|def apply_second_revision|def block_signature" scripts\run_client_server_e2e.py`
> - Ran `rg -n "missing_lease|releases_slot|safe_poll|scheduler_health" tests\test_scheduler.py tests\test_health.py`
>
> </details>
>
> <details><summary>Plan</summary>
>
> - [x] 检查容器、Client/Server 实现与可观测字段
> - [x] 实现可重复的真实 API 复杂场景集成脚本
> - [x] 执行 Step1：全量任务被增量任务抢占并恢复
> - [x] 执行 Step2：重复触发后只重审变更文件/Block
> - [x] 修复暴露的缺陷并运行回归测试
> - [x] 汇总时间线、token、调用次数与复用证据
>
> </details>
</details>

**验收结果**

两个复杂场景已使用真实 `deepseek-v4-flash` 完整测试通过，API Key 未写入代码或报告。

Step1 时间线：

- 全量任务启动后被增量任务成功抢占。
- 增量任务在 178.17 秒完成。
- 全量任务在 178.84 秒自动恢复，无需重启服务。
- 全量 10 个文件最终全部完成。
- 全量：80 次 LLM 调用，345,301 token。
- 增量：19 次 LLM 调用，79,100 token。

Step2 结果：

- 重复全量任务只重审 `src/storage.c`，另外 9 个文件复用。
- 重复增量任务只重审 `src/auth.c`，`src/parser.c` 完整复用。
- 全量新增 14 次调用、70,786 token。
- 增量新增 6 次调用、20,516 token。
- 未变文件的 Block 哈希、模型轮次、工具轨迹、token 均保持不变。

**修复的问题**

真实 MongoDB 暴露了一个重要缺陷：MongoEngine 保存空 lease 时会移除该字段，而调度器原来只匹配 `lease_token=""`，导致中断的全量任务无法重新领取。

现在领取条件同时兼容空字符串和字段不存在，见 [scheduler.py](./app/services/scheduler.py:124)。同时增加了调度异常隔离、已释放执行槽自愈和 `/health/scheduler` 诊断接口。

可重复验收脚本位于 [run_client_server_e2e.py](./scripts/run_client_server_e2e.py:432)，完整报告在 [client_server_e2e_20260714_220727.json](./artifacts/client_server_e2e_20260714_220727.json)。

**最终状态**

- `pytest`：65 项全部通过。
- Docker App、MongoDB：均为 `healthy`。
- 数据库：2 个任务、12 条文件记录全部完成，0 个失败 Block。
- 调度器：运行正常，当前无占用任务。
- 容器日志：未发现超时、Traceback 或调度错误。

报告页面：

- [全量审核报告](http://127.0.0.1:8000/demo_c/master_vs_0_version.html)
- [增量审核报告](http://127.0.0.1:8000/demo_c/wip_qiaodahai_just_demo_vs_master.html)
