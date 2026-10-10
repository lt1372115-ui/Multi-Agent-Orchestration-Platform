# 部署指南 · 出行简报（weather_agent）

> 本文档中的命令与配置项均基于当前仓库的实际文件核对得出（`Dockerfile`、`docker-compose.yml`、`default.conf`、`alembic.ini`、`uv.lock`）。
> 所有命令除特别说明外，均**在项目根目录**执行。
>
> - 想直接照做 → 看 **第 1 章「逐步执行手册」**，13 步从准备到上线，每步都有预期结果与常见问题。
> - 想查参数含义 → 看 **第 2~3 章**（前置条件、配置项）。
> - 卡住了 → 看 **第 9 章**（常见问题排查表）。

---

## 0. 先选部署形态

| 形态 | 适用场景 | 外部依赖 | 难度 |
| --- | --- | --- | --- |
| A. 裸机 + uv | 本地演示、内网服务器快速上线 | 需要 Postgres / Redis，或用 `--skip-infra` 绕过 | 低 |
| B. Docker Compose | 推荐。服务器上线、环境一致性要求高 | 只需 Docker；Postgres / Redis 由 Compose 提供 | 中 |
| C. 生产（Gunicorn + Nginx） | 公网对外、需要多进程与反代 | 同 B | 高 |

**本项目的实际依赖很轻**：天气链路只用到「和风天气 API + DeepSeek API」，数据库、Redis、Milvus、DashScope 都不是必需。但 `lifespan` 里默认会去连 Postgres 和 Redis，**不启动这两个服务就必须加 `--skip-infra`**，否则启动即报错。

---

## 1. 逐步执行手册（从准备到上线）

以下 13 步是一套可直接照做的完整流程。默认走**形态 B（Docker Compose）**，这是推荐路径；形态 A / C 的差异在 1.14 集中说明。

每一步固定给出四项：**操作** → **命令** → **预期结果** → **常见问题**。

### 步骤 1 · 确认服务器与工具链

**操作**：登录目标服务器，确认 Docker 与资源余量。

```sh
docker --version
docker compose version
df -h /var/lib/docker
free -h
```

**预期结果**：

- `Docker version 24.x` 或更高
- `Docker Compose version v2.x`（**必须 v2**，`docker compose` 子命令形式）
- `/var/lib/docker` 可用空间 ≥ 10 GB（镜像约 1.5~2 GB）
- 内存 ≥ 2 GB

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| `docker: command not found` | 未安装 Docker，先按官方文档安装，再 `sudo systemctl enable --now docker` |
| `docker compose` 报 `unknown command` | 装的是 Compose v1，改用 `docker-compose`，或升级到 v2 插件 |
| `permission denied ... docker.sock` | `sudo usermod -aG docker $USER` 后**重新登录**（不是 source 一下就行） |

### 步骤 2 · 获取代码

**操作**：把项目放到服务器的部署目录。

```sh
git clone <你的仓库地址> weather_agent
cd weather_agent
ls Dockerfile docker-compose.yml pyproject.toml uv.lock
```

**预期结果**：四个文件全部存在。`uv.lock` 尤其重要，镜像构建用 `uv sync --frozen`，缺了会直接失败。

**常见问题**：

- **本仓库当前没有初始化 git**（`git log` 报 128）。这种情况用 `scp -r` 或压缩包上传整个目录即可，不影响后续步骤。
- 上传后权限错乱导致容器读不到文件 → `chmod -R a+r .`。

### 步骤 3 · 补齐 `.dockerignore`（构建前必做）

**操作**：在项目根目录创建 `.dockerignore`，内容见 2.4。

```sh
ls .dockerignore
```

**预期结果**：文件存在。

**为什么必须在构建之前做**：`Dockerfile` 里有 `COPY src ./src`，而 `src/.env` 就躺在 `src/` 下。没有 `.dockerignore` 时：

1. **`src/.env` 会被打进镜像** —— 镜像一旦推到仓库或被人 pull，和风天气私钥与 DeepSeek Key 全部泄漏；
2. 构建上下文会包含 `.venv`（数百 MB）、各种缓存目录，构建明显变慢。

**常见问题**：如果漏做这一步且镜像已经分发出去，**按密钥泄漏处理** —— 轮换全部凭据（见第 10 章），仅删镜像不解决问题。

### 步骤 4 · 生成环境变量文件

**操作**：

```sh
cp src/.env.example src/.env
```

**预期结果**：`src/.env` 生成成功，`wc -l src/.env` 输出 100 行左右。

**常见问题**：

- Windows 上复制出的文件可能是 CRLF 换行。普通变量无所谓，但 **PEM 私钥里混入 `\r` 会导致 JWT 签名失败**。若在 Windows 上编辑，用 `dos2unix src/.env` 或编辑器切换成 LF。
- 权限过宽 → `chmod 600 src/.env`。

### 步骤 5 · 填写必改配置项

**操作**：按 3.2 的表逐条修改 `src/.env`。改完用下面这条命令自检：

```sh
grep -nE "^(ENVIRONMENT|POSTGRES_SERVER|REDIS_(CACHE|QUEUE|RATE_LIMIT)_HOST|DEEPSEEK_API_KEY|QWEATHER_API_HOST|QWEATHER_JWT_KEY_ID|QWEATHER_JWT_SUBJECT)=" src/.env
```

**预期结果**（Compose 环境下的正确取值）：

```
ENVIRONMENT=production
POSTGRES_SERVER=db
REDIS_CACHE_HOST=redis
REDIS_QUEUE_HOST=redis
REDIS_RATE_LIMIT_HOST=redis
DEEPSEEK_API_KEY=sk-xxxxxxxx
QWEATHER_API_HOST=xxxxxxxx.re.qweatherapi.com
QWEATHER_JWT_KEY_ID=xxxxxxxx
QWEATHER_JWT_SUBJECT=xxxxxxxx
```

**常见问题**：

- **最高频的错误就是 `POSTGRES_SERVER` 忘改成 `db`** —— 容器里 `localhost` 指向容器自己，不是数据库。
- 私钥写多行报解析错误 → 见 3.3 的三种写法。
- `QWEATHER_JWT_TTL_SECONDS` 被改大于 `86400` → 和风天气会拒绝鉴权（硬性要求 `exp - iat ≤ 24 小时`）。

### 步骤 6 · 把 Compose 改成生产形态

**操作**：按 5.2 改三处（删 `--reload`、删 `./src:/app/src` 挂载、加 `restart: unless-stopped`）。

**命令**（改完先验语法，不要直接起）：

```sh
docker compose config > /dev/null && echo "compose 配置合法"
```

**预期结果**：输出 `compose 配置合法`。可以再 `docker compose config | grep -A2 restart` 确认 `restart` 已生效。

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| `env file .../.env not found` | 步骤 4 没做，或路径写错（compose 里是 `./src/.env`） |
| `services.web.volumes must be a list` | YAML 缩进写错，用 `docker compose config` 定位行号 |
| 提示 `version is obsolete` | 可忽略，新 Compose 不再需要顶层 `version` 字段 |

### 步骤 7 · 构建镜像

**操作**：

```sh
docker compose build
```

**预期结果**：过程最后出现镜像命名输出（形如 `naming to docker.io/library/weather_agent-web`），退出码 0。首次构建约 3~8 分钟（取决于网络）。

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| `uv sync --frozen` 失败，提示 lock 不一致 | `uv.lock` 与 `pyproject.toml` 不同步。**不要删 `--frozen`**，在本地执行 `uv lock` 后重新提交 |
| 拉取 `ghcr.io/astral-sh/uv:...` 超时 | 配置 Docker 镜像加速或 HTTP 代理 |
| 构建上下文上传几百 MB、极慢 | 步骤 3 漏做了 |
| 构建时提示找不到 `src` | 确认在项目根目录执行，且 `Dockerfile` 与 `src/` 同级 |

### 步骤 8 · 启动全部服务

**操作**：

```sh
docker compose up -d
docker compose ps
```

**预期结果**：四个服务全部起来。`db`、`redis` 显示 `Up (healthy)`（healthcheck 需要几秒），`web`、`worker` 显示 `Up`。

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| `db` 长时间 `Up (health: starting)` | `docker compose logs db`。多为 `POSTGRES_PASSWORD`/`POSTGRES_DB` 为空，或数据卷是用旧参数初始化的（旧卷不会重新初始化） |
| `web` 反复重启 | `docker compose logs web`。最常见是 `POSTGRES_SERVER` 没改成 `db` |
| 端口 8000 被占用 | `sudo lsof -i:8000`，或改 compose 里的宿主端口映射 |
| `db` healthcheck 一直失败 | 镜像 `postgres:13` 的 `pg_isready` 用的是 `.env` 注入的 `POSTGRES_USER`，确认该变量非空 |

### 步骤 9 · 确认启动日志与建表

**操作**：

```sh
docker compose logs web | tail -30
```

**预期结果**：能看到这几行关键日志：

```
应用启动，环境=EnvironmentOption.PRODUCTION，日志级别=INFO
数据库表结构创建/校验完成，连接验证表 connection_test 已就绪
Redis 缓存连接成功: redis://redis:6379
Redis 队列连接成功: redis:6379
Milvus 未启用（ENABLE_MILVUS=false），跳过连接
```

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| `Milvus 连接失败` | `.env` 里 `ENABLE_MILVUS` 被改成 `true` 了，改回 `false`（本项目未部署 Milvus） |
| 没有建表日志 | 检查是否误设了 `SKIP_INFRA_ON_START=true` |
| `ModuleNotFoundError` | 镜像里依赖不全，`docker compose build --no-cache` 重建 |
| 日志里 `和风天气配置不完整` | 属正常（该提示只在真正调用天气接口时才抛），跳过 |

### 步骤 10 · 接口层验证

**操作**：

```sh
curl -s http://127.0.0.1:8000/api/v1/health
echo
curl -s "http://127.0.0.1:8000/api/v1/qweather/weather/10d?city=杭州" | head -c 220
echo
curl -s -o /dev/null -w "首页 HTTP %{http_code}\n" http://127.0.0.1:8000/
```

**预期结果**：

- `{"status":"ok"}`
- 返回 JSON 含 `"city"` 对象与 `"days"` 数组（10 条）
- `首页 HTTP 200`

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| 首页 404 | 镜像里没有 `src/app/static/`，检查 `Dockerfile` 是否包含 `COPY src ./src` |
| 10d 返回 500，日志有 `和风天气返回错误: 401` | JWT 配置问题，回到步骤 5 核对四个字段与私钥换行 |
| 10d 返回 `未找到城市「杭州」` | 出站网络不通或 `QWEATHER_API_HOST` 域名写错（只填域名，不要带 `https://`） |
| 请求超时无响应 | 服务器出站被墙，需放行 2.3 中的两个域名 |

### 步骤 11 · 浏览器端到端验证（含调用链路）

**操作**：浏览器打开 `http://<服务器IP>:8000/`，输入「杭州」，等天气带出图后，提问「这周末适合出门吗」。

**预期结果**（按顺序出现）：

1. 十天天气带出图，实时天气读数出现（此刻 / 湿度 / 风 / 降水 / 紫外线 …）
2. 提问后，回答气泡上方出现**「调用链路」**区块，头部显示「进行中」
3. 链路先出现节点「模型第 1 轮思考」，随后出现「正在查询「杭州」未来 10 天的天气…」并列出参数 `city=杭州  days=10`
4. 工具节点结束后去掉「正在」字样，右侧显示耗时，下方出现一行摘要，并折叠着「查看工具原始返回」
5. 回答逐字输出；链路头部最终变为「N 步 · x.xs」

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| 只有回答、完全没有链路区块 | 浏览器缓存了旧版前端。强刷 `Ctrl+F5`；静态资源版本号已升到 `?v=2`，正常会自动失效 |
| 链路停在「正在查询…」不动 | 工具侧报错。展开 `查看工具原始返回`，并查 `src/app/logs/app.log` |
| 有链路但没有「模型第 N 轮思考」节点 | 当前 LangChain 版本未发出 `on_chat_model_start`，属降级表现，功能不受影响 |
| 回答报「向导暂时联系不上」 | `DEEPSEEK_API_KEY` 为空，或服务器无法出站到 `api.deepseek.com` |
| 点「查看工具原始返回」无反应 | 该节点没有原始返回（工具报错时 `preview` 为空），属预期 |

### 步骤 12 · 接入反向代理并复验流式

**操作**：按 6.2 修改 `default.conf`，在 `docker-compose.yml` 中启用 `nginx` 服务、把 `web` 的 `ports` 换成 `expose: 8000`，然后：

```sh
docker compose up -d
curl -s -o /dev/null -w "经反代 HTTP %{http_code}\n" http://127.0.0.1/
```

**预期结果**：`经反代 HTTP 200`，且经反代访问时回答仍然**逐字**输出。

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| 回答憋很久然后一次性刷出 | `proxy_buffering off;` 没生效或没重载 Nginx |
| 约 60 秒后连接断开 | `proxy_read_timeout` 未改（默认 60s），按 6.2 设为 300s |
| 反代 502 | `nginx` 与 `web` 不在同一 compose 网络，或 `proxy_pass` 里的主机名不是 `web` |
| 页面样式丢失 | `/static` 被反代规则吞掉，确认 `location /` 覆盖了静态路径 |

### 步骤 13 · 上线收尾

**操作**：

```sh
# 1) 确认重启策略生效：重启后服务自动回来
docker compose restart && sleep 5 && docker compose ps

# 2) 确认生产环境已关闭文档接口，期望输出 404
curl -s -o /dev/null -w "/docs HTTP %{http_code}\n" http://127.0.0.1/docs

# 3) 确认数据卷名称并做一次备份
docker volume ls | grep postgres
docker run --rm -v weather_agent_postgres-data:/data -v "$(pwd)":/backup alpine \
  tar czf "/backup/pg-$(date +%F).tar.gz" -C /data .
```

**预期结果**：

- 重启后四个服务仍为 `Up`
- `/docs HTTP 404`（`ENVIRONMENT=production` 生效）
- `docker volume ls` 能列出 `..._postgres-data`，备份命令在项目根目录生成 `pg-YYYY-MM-DD.tar.gz`

**常见问题**：

| 现象 | 处理 |
| --- | --- |
| `/docs` 返回 200 | `ENVIRONMENT` 还不是 `production`，改完需 `docker compose up -d` 让容器重新注入环境变量 |
| `docker volume ls` 没找到卷 | 卷名前缀是 compose 项目名（默认取目录名），用 `docker volume ls \| grep postgres` 确认真实名称 |
| 备份文件为 0 字节 | 卷挂载路径错，Postgres 数据在容器内 `/var/lib/postgresql/data` |

### 第 1 章补充 · 形态 A / 形态 C 的步骤差异

前面 13 步走完后，只有这几处不同：

**形态 A（裸机 + uv）** —— 替换步骤 6~9：

```sh
uv sync                                          # 代替 docker compose build
uv run python src/run.py --host 0.0.0.0 --port 8888 --no-reload
# 无 Postgres / Redis 时：
uv run python src/run.py --skip-infra
```

- 步骤 5 的 `POSTGRES_SERVER` 要填 `localhost`（不是 `db`），三个 `REDIS_*_HOST` 同理。
- 没有 Compose 的重启策略，需要自己用 systemd 托管（见 4.2）。
- 服务在 8888 端口，步骤 10~11 的 URL 相应改成 `:8888`。

**形态 C（Gunicorn + Nginx）** —— 在步骤 12 之后追加：

- 多进程启动改用 `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4`（原因见 6.1）。
- 必须部署到 Linux：**gunicorn 不支持 Windows**。
- 步骤 13 追加 HTTPS 证书配置。

---

## 2. 前置条件

### 2.1 运行环境

| 项 | 要求 | 说明 |
| --- | --- | --- |
| Python | **3.13** | 由 `.python-version` 固定，uv 会自动装，不必手动准备 |
| uv | 0.11+ | 依赖管理与运行入口，见 README 安装章节 |
| Docker | 24+ / Compose v2 | 仅形态 B、C 需要。本机已验证 Docker 29.7.2 |
| 操作系统 | Linux / macOS / Windows | Windows 下 gunicorn 不可用，形态 C 建议部署到 Linux |

本机当前状态（已核对）：`uv 0.11.16`、`Docker 29.7.2`、`Python 3.13.14`、`.venv` 已存在 → **形态 A 可以直接开跑**。

### 2.2 必须申请的外部凭据

| 凭据 | 必填性 | 获取方式 |
| --- | --- | --- |
| 和风天气 JWT 凭据 | **必须** | 控制台创建 Ed25519 凭据 → 得到 `KEY_ID`、私钥；再拿到 `SUBJECT`（项目 ID）、`ISSUER`（开发者 ID）与**API Host 订阅域名** |
| DeepSeek API Key | **必须** | `/chat`、`/travel-advice` 依赖它；缺失时接口返回错误但不影响启动 |
| PostgreSQL | 可选 | 天气链路不用。不部署就加 `--skip-infra` |
| Redis | 可选 | 同上。缓存 / ARQ / 限流均未在天气链路中使用 |
| Milvus | **不需要** | 保持 `ENABLE_MILVUS=false` 即可，不会发起连接 |
| DashScope | **不需要** | 仅 `core/embeddings.py` 使用，天气链路未调用 |

> 和风天气新版的硬性约束：`exp - iat` **不得超过 24 小时**，所以 `QWEATHER_JWT_TTL_SECONDS` 不要改大于 `86400`，否则 API 会拒绝鉴权。

### 2.3 网络与端口

| 方向 | 目标 | 用途 |
| --- | --- | --- |
| 出站 443 | `*.re.qweatherapi.com` | 天气数据 |
| 出站 443 | `api.deepseek.com` | 大模型 |
| 入站 | `8888`（裸机 dev）/ `8000`（容器）/ `80`（Nginx） | 对外服务 |

> 若服务器有出口白名单，必须放行上述两个域名，否则页面能打开但查询天气和对话会失败。

### 2.4 部署前建议补齐的文件 `.dockerignore`

仓库**没有 `.dockerignore`**，会导致两个问题：构建上下文把 `.venv`、`.mypy_cache`、`.pytest_cache` 全部上传（构建变慢），同时 `COPY src ./src` 会把 **`src/.env` 连同真实密钥一起打进镜像**。在根目录新建 `.dockerignore`：

```gitignore
.venv/
__pycache__/
*.py[cod]
.mypy_cache/
.ruff_cache/
.pytest_cache/
tests/
storage/
src/.env
src/app/logs/
新建文件夹/
.git/
```

---

## 3. 配置项设置

### 3.1 生成配置文件

```sh
cp src/.env.example src/.env
```

### 3.2 必须修改的项（逐条核对，不要漏）

| 变量 | 示例值 | 说明 |
| --- | --- | --- |
| `ENVIRONMENT` | `production` | `production` 会**关闭** `/docs`、`/redoc`、`/openapi.json`；演示环境填 `local` |
| `SECRET_KEY` | `openssl rand -hex 32` 生成 | 示例值是占位符，必须替换 |
| `DEEPSEEK_API_KEY` | `sk-...` | 必填 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 保持默认 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 保持默认 |
| `QWEATHER_JWT_PRIVATE_KEY` | PEM 全文 | **见 3.3 换行说明** |
| `QWEATHER_JWT_KEY_ID` | 控制台凭据 ID | 必填 |
| `QWEATHER_JWT_SUBJECT` | 项目 ID | 必填 |
| `QWEATHER_JWT_ISSUER` | 开发者 ID | API Host 订阅场景必填 |
| `QWEATHER_API_HOST` | `xxxxxx.re.qweatherapi.com` | 只填域名，代码会自动加 `https://` |
| `POSTGRES_SERVER` | 裸机 `localhost` / Compose `db` | **Compose 下必须是 `db`，这是最常见的踩坑点** |
| `REDIS_*_HOST` | 裸机 `localhost` / Compose `redis` | 三个 `REDIS_*_HOST` 都要改 |
| `POSTGRES_PASSWORD` | 强密码 | Compose 下该值同时决定 Postgres 容器初始化密码 |

### 3.3 私钥换行的三种写法

`.env` 里无法直接写多行值，三种写法任选：

```dotenv
# 写法一：用 \n 表示换行（代码会自动还原，最省事）
QWEATHER_JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMC4CAQAw...\n-----END PRIVATE KEY-----"

# 写法二：真实换行 + 引号（当前 .env.example 用的就是这种）
QWEATHER_JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
MC4CAQAw...
-----END PRIVATE KEY-----"
```

### 3.4 配置补充说明

- `LOG_LEVEL=INFO` 正常，排查问题时改 `DEBUG`；`DB_ECHO=true` 会打印所有 SQL，生产别开。
- `DOCUMENT_DIR=G:/Rag知识库` 是**示例里的 Windows 路径**，Linux 下指向无效目录。天气链路不读它，暂时无影响，但建议改成项目内相对目录或直接留空。
- `MILVUS_*` / `AUTO_CREATE_RAG_COLLECTIONS` 保持 `false`。
- `src/.env` 已在 `.gitignore` 中，不会被提交。

---

## 4. 形态 A：裸机 + uv

### 4.1 安装与启动

```sh
uv sync
```

可选的数据库依赖：

```sh
docker run -d --name postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=fastapi_template postgres:16
docker run -d --name redis -p 6379:6379 redis:alpine
```

启动：

```sh
# 有 Postgres / Redis
uv run python src/run.py --host 0.0.0.0 --port 8888 --no-reload

# 没有 Postgres / Redis（天气功能完全可用）
uv run python src/run.py --skip-infra
```

生产服务器建议 `--no-reload`（`run.py` 默认开热重载，属开发行为）。

`src/app/static/` 存在时，应用会在 `/` 托管出行简报页面，静态资源挂在 `/static`。这是天气项目的实际入口，**不是** `/docs`。

### 4.2 用 systemd 托管（可选）

形态 A 没有 Compose 的重启策略，长期运行建议写一个 unit：

```ini
[Unit]
Description=weather_agent FastAPI
After=network.target

[Service]
WorkingDirectory=/opt/weather_agent
ExecStart=/opt/weather_agent/.venv/bin/python src/run.py --host 0.0.0.0 --port 8888 --no-reload
Restart=unless-stopped

[Install]
WantedBy=multi-user.target
```

---

## 5. 形态 B：Docker Compose（推荐）

### 5.1 启动

```sh
docker compose up --build -d
docker compose logs -f web
```

会拉起四个服务：`web`（FastAPI，宿主 8000）、`worker`（ARQ）、`db`（Postgres）、`redis`。

### 5.2 部署前必须调整的三处 Compose 配置

当前 `docker-compose.yml` 是**开发形态**，直接上线有三处要改：

1. **关掉热重载**：`web.command` 里的 `--reload` 删掉。
2. **去掉源码挂载**：`web` 与 `worker` 的 `volumes: ./src:/app/src` 会让容器用宿主机源码覆盖镜像内容，生产应删除，改为依赖镜像构建。
3. **加重启策略**：给 `web`、`worker`、`db`、`redis` 加 `restart: unless-stopped`，否则服务器重启后服务不会自动起来。

另外注意：`db` 用的是 `postgres:13`（README 里写的是 16）。不影响运行，但新部署建议统一到 `postgres:16` 并确认数据卷是新建的（旧版本数据卷不能直接被新版挂载）。

### 5.3 验证

```sh
docker compose ps
curl -s http://127.0.0.1:8000/api/v1/health     # {"status":"ok"}
curl -s http://127.0.0.1:8000/ | head -c 80      # 出行简报页面 HTML
```

---

## 6. 形态 C：生产（Gunicorn + Nginx）

### 6.1 多进程启动

`Dockerfile` 第 39 行给了 gunicorn 的注释示例。两点注意：

- 当前锁定的是 `uvicorn 0.52.4`，`uvicorn.workers` 模块**仍存在但已弃用**，导入会打 `DeprecationWarning`。更干净的做法是直接用 uvicorn 自带的多进程：

  ```sh
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
  ```

- gunicorn **不支持 Windows**，形态 C 请部署到 Linux。

### 6.2 Nginx 配置必须补 SSE 相关项

`default.conf` 目前只有基础反代，**缺少流式响应所需的三项配置**。`/chat` 是 SSE 长连接，不改会出现「回答卡住不输出」或「60 秒后断开」：

```nginx
server {
    listen 80;
    # 大模型首字延迟可能超过 1 分钟，必须放宽
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    location / {
        proxy_pass http://web:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

> 接口已经在响应头里设置了 `X-Accel-Buffering: no`，能关掉 Nginx 的响应缓冲；但 `proxy_read_timeout` 默认 60 秒是**必须手动放宽**的。

同时在 `docker-compose.yml` 中：`web` 的 `ports` 注释掉、改用 `expose`，再打开 `nginx` 服务与 `web` 的 `expose: 8000`。

### 6.3 上线前收尾

- `ENVIRONMENT=production`（自动关闭文档接口）。
- 数据卷 `postgres-data`、`redis-data` 必须做持久化备份。
- 如需 HTTPS，在 Nginx 层加证书，或前置云负载均衡。

---

## 7. 数据库迁移说明

`src/migrations/versions/` 目前**只有 README，没有任何迁移版本**。应用启动时靠 `Base.metadata.create_all()` 自动建表（含连接验证表 `connection_test`），所以：

- 首次部署**不需要**执行 Alembic，直接启动即可。
- 后续模型变更时再启用：

  ```sh
  uv run alembic revision --autogenerate -m "your change"
  uv run alembic upgrade head
  ```

- `src/migrations/env.py` 是 Alembic 内部钩子，**不要**用 `python src/migrations/env.py` 直接执行。
- 想在容器里跑迁移，把 `docker-compose.yml` 末尾注释掉的 `pytest` 服务块按同样写法加一个 `migrate` 服务即可。

---

## 8. 上线验证清单

按顺序走一遍，全绿再交付（与第 1 章步骤 10~11 对应）：

1. `curl /api/v1/health` → `{"status":"ok"}`
2. 浏览器打开 `/` → 出行简报页面正常渲染，无 404 静态资源
3. 输入「杭州」→ 十天天气带出图、实时天气读数出现
4. 提问「这周末适合出门吗」→ 气泡上方出现「调用链路」，先「模型第 1 轮思考」，再「正在查询「杭州」未来 10 天的天气…」，随后逐字输出回答
5. `curl /docs` → **404**（`ENVIRONMENT=production` 生效）
6. 服务器日志（`src/app/logs/app.log`）无 `Milvus 连接失败`、无 `DeepSeek 配置不完整`
7. 反向代理/HTTPS 下重放第 3、4 步，确认 SSE 不被缓冲

---

## 9. 常见问题与处理

| 现象 | 根本原因 | 处理方式 |
| --- | --- | --- |
| 启动即报连接 Postgres 失败 | `lifespan` 默认执行 `create_tables()` | 加 `--skip-infra`（裸机），或在 Compose 里带上 `db` 服务 |
| Compose 下 web 连不上数据库 | `.env` 里 `POSTGRES_SERVER` 还是 `localhost` | 改为 `db`；Redis 三项同理改为 `redis` |
| 页面能开但查天气报 `401` / `和风天气返回错误` | JWT 配置缺失或私钥换行丢失 | 核对 `KEY_ID`/`SUBJECT`/`ISSUER`/`API_HOST`，确认 PEM 完整 |
| 和风天气返回鉴权错误但配置看着没错 | `exp - iat` 超过 24 小时 | `QWEATHER_JWT_TTL_SECONDS` 保持 ≤ 86400 |
| 对话一直转圈、不输出 | 反向代理缓冲 / 读超时 | 按 6.2 补 `proxy_buffering off`、`proxy_read_timeout 300s` |
| 对话 60 秒后被切断 | Nginx 默认 `proxy_read_timeout 60s` | 同上 |
| 对话报「暂时联系不上」 | `DEEPSEEK_API_KEY` 为空或服务器无法出站到 `api.deepseek.com` | 检查密钥与出口白名单 |
| 同一问题答案明显是旧的 | `ClientCacheMiddleware` 把所有响应统一改写成 `Cache-Control: public, max-age=60`，**会覆盖路由自己设的 `no-cache`** | 临时把 `CLIENT_CACHE_MAX_AGE` 调小；注意该中间件对未来的鉴权接口也有「公开可缓存」风险 |
| 看不到工具调用链路 | 浏览器缓存了旧版 `app.js` | 静态资源版本号现在由后端按文件修改时间**自动生成**，普通刷新即可；若仍异常请强刷 `Ctrl+F5` |
| `curl` 本机接口报 `upstream connect failed` | 系统代理拦截了回环地址 | `curl` 加 `--noproxy '*'`，或在代理软件里给 `localhost`/`127.0.0.1` 设置直连例外 |
| 浏览器看到的还是旧页面 | `max-age=60` 内的静态资源缓存窗口 | 刷新一次即可；改完前端后版本号自动变化，无需再手动改 `index.html` |
| 镜像构建特别慢 | 无 `.dockerignore`，构建上下文包含 `.venv` 等 | 按 2.4 建 `.dockerignore` |
| Windows 上 `gunicorn` 命令不存在 | gunicorn 不支持 Windows | 改用 `uvicorn --workers N`，或部署到 Linux |
| 容器重启后服务没起来 | Compose 未配重启策略 | 加 `restart: unless-stopped` |
| 跑 `pytest` 时 `client` 相关用例失败 | `tests/conftest.py` 的 `client` fixture 会连 Postgres | 先起 Postgres；`pytest tests/test_agent_events.py` 不依赖任何外部服务，可随时跑 |

---

## 10. 部署前必须处理的安全事项

1. **`.env.example` 中写有真实的和风天气 Ed25519 私钥**（含 `KEY_ID`、`SUBJECT`、`ISSUER`、`API_HOST`）。该文件会随仓库分发。**上线前请到和风天气控制台轮换密钥，并把 `.env.example` 内的值替换为占位符。**
2. 无 `.dockerignore` 时 `src/.env` 会被打进镜像 → 镜像一旦推送到仓库，密钥即泄漏。务必按 2.4 补齐。
3. `SECRET_KEY` 必须替换示例值。
4. `ENVIRONMENT=production` 关闭文档接口，避免暴露内部结构。
5. `src/app/logs/` 未被 `.gitignore` 忽略，日志可能带着请求内容被提交，建议补一条忽略规则。

---

## 11. 快速命令速查

```sh
uv sync                                              # 装依赖
uv run python src/run.py --skip-infra                # 无外部依赖直接起服务
uv run python src/run.py --host 0.0.0.0 --no-reload  # 服务器裸机
docker compose build                                 # 构建镜像
docker compose up -d                                 # 容器化启动
docker compose ps                                    # 查看服务状态
docker compose logs -f web                           # 跟踪 web 日志
docker compose config > /dev/null                    # 校验 compose 配置
docker compose restart                               # 重启全部服务
uv run arq app.logs.core.worker.settings.WorkerSettings   # 单启 ARQ worker
uv run alembic upgrade head                          # 应用迁移（当前为空）
uv run python -m pytest tests/test_agent_events.py   # 跑不依赖外部服务的测试
```
