# Jenkins 与 GitLab 部署说明

## 1. 流水线职责

仓库提供三个 Pipeline Script Path：

| Jenkins Job | Script Path | 用途 |
|---|---|---|
| `code-review-trigger` | `jenkins/Jenkinsfile.review-trigger` | 接收五个审核参数并调用 `scripts/jenkins_trigger.py` |
| `code-review-ci` | `jenkins/Jenkinsfile.develop` | 所有分支运行单元测试；`develop`、`development`、`master` 部署开发环境 |
| `code-review-production` | `jenkins/Jenkinsfile.production` | 输入 master 开发部署显示的短 SHA，发布到生产环境 |

推荐把第二个 Job 建成 GitLab Multibranch Pipeline。GitLab Merge Request 和普通分支都会运行测试，但只有开发分支和 master 会部署开发环境。

master 开发部署成功后会完成两件事：

1. 推送 `release-<40位完整SHA>` 镜像标签。
2. 把 Jenkins 构建名称设置为 `#<BUILD_NUMBER> <8位短SHA>`。

生产流水线只接受能够唯一解析、属于 `origin/master`、并且已经存在对应 release 镜像的提交。因此，用户看到短 SHA 并不代表生产直接信任短字符串；流水线内部始终使用完整 SHA。

## 2. Jenkins 前置配置

### 2.1 Agent

审核触发 Job 使用标签 `linux-python`，该 Agent 需要：

- Git
- Python 3.12

开发和生产 Job 使用标签 `linux-docker`，该 Agent 需要：

- Linux
- Git、Docker Engine、Docker Compose v2
- `gzip`、`sha256sum`、`ssh`、`scp`
- 访问公司 GitLab Container Registry 的网络权限

### 2.2 Jenkins 插件

- Pipeline
- Git
- GitLab Branch Source
- Credentials Binding
- Pipeline Utility Steps，第一条流水线使用其中的 `readJSON`
- Timestamper

### 2.3 Credentials

在 Jenkins Credentials 中创建：

| Credentials ID | 类型 | 权限 |
|---|---|---|
| `gitlab-registry-push` | Username with password | GitLab Deploy Token，`read_registry` + `write_registry` |
| `gitlab-registry-read` | Username with password | GitLab Deploy Token，仅 `read_registry` |
| `dev-deploy-ssh` | SSH Username with private key | 开发服务器部署账号 |
| `prod-deploy-ssh` | SSH Username with private key | 生产服务器部署账号 |
| `deploy-known-hosts` | Secret file | 包含开发、生产服务器公钥的 `known_hosts` 文件 |

部署私钥建议使用专用、无交互口令的受限账号密钥。不要使用 `StrictHostKeyChecking=no`。

### 2.4 Jenkins 全局环境变量

在 `Manage Jenkins -> System -> Global properties` 配置：

```text
CODE_REVIEW_SERVER_URL=http://code-review.internal:8000
CI_IMAGE_REPOSITORY=gitlab.internal.example/ai/ci-ai-codereview
PYTHON_BASE_IMAGE=gitlab.internal.example/base/python:3.12-slim@sha256:<digest>

DEV_DEPLOY_HOST=dev-code-review.internal
DEV_DEPLOY_PORT=22
DEV_DEPLOY_ROOT=/opt/ci-ai-codereview/dev

PROD_DEPLOY_HOST=prod-code-review.internal
PROD_DEPLOY_PORT=22
PROD_DEPLOY_ROOT=/opt/ci-ai-codereview/prod

PROD_APPROVERS=release-manager,ops-team
```

`PROD_APPROVERS` 可不配置；配置后，只有列出的 Jenkins 用户或组可以确认生产发布。

`PYTHON_BASE_IMAGE` 应指向与 `CI_IMAGE_REPOSITORY` 相同公司 Registry 中同步的 Python 3.12 基础镜像，生产级配置建议使用 digest，而不是可移动 tag。未配置时回退到 `python:3.12-slim`。流水线使用临时 `DOCKER_CONFIG` 登录和清理凭据，Multibranch 并发构建不会共享 Jenkins Agent 的 Docker 登录文件。

## 3. 部署服务器初始化

开发、生产服务器均需要 Docker Engine、Docker Compose v2 和 `flock`（通常由 `util-linux` 提供）。部署账号必须能执行 Docker 命令，并拥有对应部署根目录。

以生产环境为例：

```bash
mkdir -p /opt/ci-ai-codereview/prod/shared
mkdir -p /srv/ci-ai-codereview/repositories
chmod 700 /opt/ci-ai-codereview/prod/shared
```

创建 `/opt/ci-ai-codereview/prod/shared/app.env`，该文件不进入 Git：

```dotenv
APP_ENV=prod
MONGODB_URI=mongodb://mongo.internal:27017/ci_ai_codereview
MONGODB_DB=ci_ai_codereview
MONGO_MOCK=false

LLM_URL=https://llm.internal/v1
LLM_API_KEY=replace-with-secret
LLM_MODEL=replace-with-model
LLM_MOCK_ENABLED=false

SCHEDULER_INTERVAL_SECONDS=5
SCHEDULER_LEASE_SECONDS=120
SCHEDULER_SHUTDOWN_GRACE_SECONDS=330
LLM_TIMEOUT_SECONDS=300
LLM_FILE_TIMEOUT_SECONDS=900
LLM_CONCURRENCY=4
```

创建 `/opt/ci-ai-codereview/prod/shared/deploy.env`：

```dotenv
CODE_REPOSITORY_HOST_ROOT=/srv/ci-ai-codereview/repositories
PUBLIC_BIND_ADDRESS=0.0.0.0
PUBLIC_PORT=8000
HEALTH_TIMEOUT_SECONDS=180
APP_STOP_GRACE_PERIOD=360s
DEPLOY_LOCK_TIMEOUT_SECONDS=900

# 内网不能访问 Docker Hub 时，必须改为公司镜像仓库中的 nginx 镜像。
GATEWAY_IMAGE=gitlab.internal.example/base/nginx:1.27-alpine
```

然后使用仅有 `read_registry` 权限的 GitLab Deploy Token，在部署服务器提前登录 Registry：

```bash
printf '%s' "$GITLAB_DEPLOY_TOKEN" | docker login gitlab.internal.example \
  --username "$GITLAB_DEPLOY_USER" --password-stdin
```

开发环境使用同样结构，只需把根目录替换为 `DEV_DEPLOY_ROOT`，并使用开发环境 MongoDB、LLM 和端口配置。

## 4. 三个 Job 的创建方式

### 4.1 审核触发 Job

1. 新建 Pipeline。
2. Definition 选择 `Pipeline script from SCM`。
3. SCM 选择公司 GitLab 中的本仓库。
4. Script Path 填 `jenkins/Jenkinsfile.review-trigger`。
5. 第一次运行后会显示五个业务参数。

参数中的 `REVIEW_VERSION_PATH` 和 `COPY_FROM_VERSION_PATH` 必须是审核 server 容器可见的路径，例如 `/repositories/demo_c/master`，不能直接填写 Jenkins Agent 的临时 workspace。

### 4.2 开发 CI/CD Job

1. 新建 Multibranch Pipeline。
2. Branch Source 选择 GitLab，配置仓库和 checkout credential。
3. Script Path 填 `jenkins/Jenkinsfile.develop`。
4. 配置 GitLab webhook 或定期索引。
5. 建议发现所有分支和 Merge Request，但对 master 设置保护规则，只允许 MR 合并。

行为如下：

- feature/MR：构建镜像并在相同 Python 3.12 镜像中运行 pytest，不部署。
- develop/development：测试、发布完整 SHA 镜像、部署开发环境。
- master：完成上述步骤，开发部署成功后再发布 release 镜像，并显示短 SHA。

### 4.3 生产 Job

1. 新建普通 Pipeline，禁止 SCM 自动触发。
2. Definition 选择 `Pipeline script from SCM`，固定使用 master。
3. Script Path 填 `jenkins/Jenkinsfile.production`。
4. 从第二条流水线成功的 master 记录中取得短 SHA，填入 `COMMIT_SHORT`。
5. 流水线验证提交和镜像后，会等待人工确认。

生产 Job 不重新构建镜像。它部署的是已经通过相同提交单元测试和开发环境验证的 `release-<完整SHA>` 镜像，同时通过 `git archive` 生成该提交的源码快照、SHA-256 校验文件并 SCP 到生产服务器。

## 5. 蓝绿部署原理

`deploy/blue_green_deploy.sh` 管理以下容器：

- `web-blue` / `web-green`：FastAPI，关闭 scheduler。
- `worker-blue` / `worker-green`：同一镜像，开启 scheduler，不对外暴露端口。
- `gateway`：稳定的 Nginx 入口，对外提供 `PUBLIC_PORT`。

一次发布顺序为：

1. 拉取不可变 release 镜像。
2. 启动非活动颜色的 web 和 worker。
3. 等待两个容器 `/health` 成功。
4. 生成新 Nginx upstream，执行 `nginx -t`。
5. 平滑 reload Nginx，并再次从 gateway 验证 `/health`。
6. 写入 active slot、镜像和完整 commit 状态。
7. 优雅停止旧 worker；旧 web 暂时保留，用于旧连接排空和快速回滚。

部署脚本持有 `<DEPLOY_ROOT>/state/deploy.lock` 文件锁，因此 develop 与 master 即使在 Multibranch Job 中同时完成，也不会并发修改同一开发环境。

MongoDB 不随应用发布重建。两个颜色共享同一个 MongoDB 和只读代码仓库目录。

## 6. 是否存在宕机时间

蓝绿拓扑安装完成后，正常发布的 HTTP 宕机时间为 0：只有新容器健康后才 reload Nginx，Nginx reload 本身会保留旧 worker process 处理已有连接。

审核 worker 与 HTTP 服务是分开的。旧 worker 收到 SIGTERM 后会停止领取新任务，并等待当前审核到达可中断检查点。推荐让 `SCHEDULER_SHUTDOWN_GRACE_SECONDS` 至少比 `LLM_TIMEOUT_SECONDS` 大 30 秒，并让 `APP_STOP_GRACE_PERIOD` 再比前者大 30 秒；上面的 330/360 秒适配单次 LLM 300 秒超时。若请求仍超过该窗口，容器可能被强制结束，但 Block 已逐块落库，任务会在 lease 过期后被新 worker 继续领取。此时影响是后台审核出现短暂延迟，不是报告/API 不可用，也不会丢失已完成 Block。

从当前“app 容器直接占用 8000”迁移到 gateway 的第一次发布是例外，因为两个进程不能同时绑定 8000：

- 有公司负载均衡/VIP时：先把新 gateway 配到临时端口，健康后切换负载均衡，可做到无中断。
- 只有单机端口时：第一次需要停止旧 app 再启动 gateway，通常有数秒维护窗口；之后的发布均走蓝绿切换。

## 7. 回滚

状态文件位于：

```text
<DEPLOY_ROOT>/state/active-slot
<DEPLOY_ROOT>/state/active-image
<DEPLOY_ROOT>/state/active-commit
<DEPLOY_ROOT>/state/previous-image
```

标准回滚方式是重新运行生产 Job，输入上一个 master 发布的短 SHA。旧源码快照保存在 `<DEPLOY_ROOT>/releases/<完整SHA>`，旧 web 容器也会保留到该颜色下次被复用。

## 8. GitLab Registry 建议

- 对 `release-.*` 设置 Protected Container Tag 规则，仅允许发布账号写入。
- GitLab 版本支持 immutable container tags 时，对 `^release-[0-9a-f]{40}$` 设置不可变规则。
- 生产服务器只使用 `read_registry` Deploy Token。
- master、develop 分支启用保护和 MR 审批，不允许直接 push。
