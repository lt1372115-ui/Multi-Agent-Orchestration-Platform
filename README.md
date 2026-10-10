# FastAPI 后端开发模板

一个基于 **FastAPI + SQLAlchemy + Pydantic v2** 的异步后端项目模板，使用 [uv](https://docs.astral.sh/uv/) 管理依赖，开箱即用。

本模板面向希望快速启动新 API 服务的团队与个人，内置了分层目录结构、配置管理、异步数据库会话、Redis 缓存、任务队列（ARQ）、客户端缓存中间件、限流工具以及 Docker 化部署配置。你只需要克隆、改配置，然后开始写业务代码。

## 技术栈

- [FastAPI](https://fastapi.tiangolo.com/)：现代 Python Web 框架
- [Pydantic v2](https://docs.pydantic.dev/)：数据校验与配置管理
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/)：异步 ORM
- [PostgreSQL](https://www.postgresql.org/)：关系型数据库
- [Redis](https://redis.io/)：缓存 / 队列 / 限流
- [ARQ](https://arq-docs.helpmanual.io/)：基于 asyncio 与 Redis 的任务队列
- [LangChain](https://python.langchain.com/)：RAG 编排与文档处理
- [LangGraph](https://langchain-ai.github.io/langgraph/)：Agent 工作流编排
- [uv](https://docs.astral.sh/uv/)：快速、可靠的 Python 包与项目管理器
- [Docker Compose](https://docs.docker.com/compose/)：一键启动全部服务

## 已内置的能力

- ⚡️ 全异步：FastAPI + SQLAlchemy 异步引擎 + asyncpg
- 🧱 清晰分层：`api / core / db / middleware` 目录结构，便于扩展
- 🗄️ 异步数据库会话与 `Base` 声明基类
- 🏬 Redis 缓存连接池与缓存装饰器
- 🚦 ARQ 后台任务队列（含 worker 入口与示例任务）
- 🛑 限流工具（Redis 计数器实现）
- 👜 客户端缓存中间件（`Cache-Control` 头）
- ⚙️ 基于环境的 API 文档开关（local / staging / production）
- 🐳 Dockerfile 与 docker compose 配置（web / worker / db / redis）
- 🧪 pytest、ruff、mypy 与 pre-commit 配置

## 开箱即用范围说明

本模板定位为「**基础设施 + 工程规范开箱即用，业务代码按需实现**」：

- ✅ **已经就绪**：uv 依赖管理、分层目录、配置系统、异步数据库会话、Redis 缓存/队列/限流连接、ARQ worker、客户端缓存中间件、日志、健康检查、Docker 编排、测试与静态检查工具链。
- 🧩 **预留待实现**：用户认证（JWT）、登录/登出、用户 CRUD、套餐/限流策略、超级用户创建脚本等业务能力。相关工具（`fastcrud`、`pyjwt`、`python-multipart` 等）已安装，`src/scripts/` 中提供了 `create_first_superuser.py`、`create_first_tier.py` 占位脚本，按需填充即可。

## 环境要求

- Python **3.13**
- [uv](https://docs.astral.sh/uv/getting-started/installation/)（推荐）
- Docker 与 Docker Compose（使用容器化部署时需要）
- PostgreSQL 与 Redis（本地开发时可以通过 Docker 启动，见下文）

## 安装 uv

### Windows

**方式一：官方安装脚本（推荐）**

打开 PowerShell，执行：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装完成后，**关闭当前 PowerShell 窗口并重新打开**，使环境变量生效，然后验证：

```powershell
uv --version
```

**方式二：使用 pip 安装**

如果你已经安装了 Python 与 pip：

```powershell
pip install uv
```

**方式三：使用 winget 安装**

```powershell
winget install --id=astral-sh.uv -e
```

> Windows 常见问题：
>
> - 如果提示 `uv : 无法将"uv"项识别为 cmdlet...`，说明 uv 未安装或安装后没有重开终端。
> - 如果安装脚本被网络/代理拦截，可以改用 pip 安装，或从 [uv releases](https://github.com/astral-sh/uv/releases) 下载对应的 `uv-x86_64-pc-windows-msvc.zip` 后手动解压并加入 `PATH`。

### macOS

**方式一：官方安装脚本（推荐）**

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装后重新打开终端或执行：

```sh
source "$HOME/.local/bin/env"
uv --version
```

**方式二：使用 Homebrew 安装**

```sh
brew install uv
```

**方式三：使用 pip / pipx 安装**

```sh
pip install uv
# 或
pipx install uv
```

### 验证与基本用法

安装成功后，进入项目目录并安装依赖：

```sh
cd D:\project\FastAPi_Template   # Windows
cd ~/path/to/FastAPi_Template    # macOS/Linux

uv sync
```

uv 会根据项目根目录的 `.python-version`（`3.13`）自动管理 Python 解释器，并根据 `pyproject.toml` 与 `uv.lock` 创建虚拟环境并安装依赖，无需手动安装 Python 3.13。

## 快速开始

### 1. 克隆模板

```sh
git clone <your-repo-url> my-project
cd my-project
```

### 2. 安装依赖

uv 会读取 `.python-version` 与 `pyproject.toml`，自动创建虚拟环境并安装依赖：

```sh
uv sync
```

### 3. 准备环境变量

复制示例配置，并按需修改：

```sh
cp src/.env.example src/.env
```

关键配置项：

| 变量 | 说明 |
| --- | --- |
| `POSTGRES_SERVER` | 数据库地址；Docker Compose 中填 `db`，本地填 `localhost` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | 数据库账号、密码与库名 |
| `SECRET_KEY` | JWT 签名密钥，使用 `openssl rand -hex 32` 生成 |
| `REDIS_CACHE_HOST` / `REDIS_QUEUE_HOST` | Redis 地址，Docker Compose 中填 `redis` |
| `ENVIRONMENT` | `local` / `staging` / `production`，影响文档接口是否开放 |
| `LOG_LEVEL` | 日志级别，可选 `DEBUG` / `INFO` / `WARNING` / `ERROR`，默认 `INFO` |
| `DB_ECHO` | 是否打印 SQLAlchemy 生成的 SQL 语句，默认 `false` |

### 4. 启动依赖服务（PostgreSQL 与 Redis）

最简单的方式是使用 Docker：

```sh
docker run -d --name postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
docker run -d --name redis -p 6379:6379 redis:alpine
```

### 5. 启动 API

```sh
uv run python src/run.py
```

本地服务默认监听 **8888** 端口：

- 打开 [http://127.0.0.1:8888/docs](http://127.0.0.1:8888/docs) 查看交互式文档
- 健康检查：`curl http://127.0.0.1:8888/api/v1/health`

> 如果暂时没有启动 PostgreSQL / Redis，可以先跳过外部依赖快速预览接口：
>
> ```sh
> uv run python src/run.py --skip-infra
> ```
>
> 该模式下服务可正常启动并访问 `/docs` 与 `/api/v1/health`，但数据库、缓存、队列相关接口需要依赖就绪后才能使用。

验证服务是否正常：

```sh
curl http://127.0.0.1:8888/api/v1/health
```

返回：

```json
{ "status": "ok" }
```

## 使用 Docker Compose 一键启动

在项目根目录执行：

```sh
docker compose up
```

该命令会同时启动：

- `web`：FastAPI 应用，默认监听 `8000` 端口
- `worker`：ARQ 后台任务 worker
- `db`：PostgreSQL
- `redis`：Redis

`src/.env` 会通过 `env_file` 注入到容器。注意：使用 Docker Compose 时，数据库与 Redis 地址应分别配置为 `db` 与 `redis`。

## 常用命令

```sh
uv sync                                        # 安装/同步依赖
uv run python src/run.py                       # 本地启动 API（默认 8888 端口）
uv run python src/run.py --skip-infra           # 无 Postgres/Redis 时快速启动
uv run python -m pytest                        # 运行测试
uv run ruff check --fix && uv run ruff format  # 修复并格式化代码
uv run mypy src tests                                # 类型检查（含测试）
uv run alembic revision --autogenerate -m "..." # 在项目根目录生成数据库迁移
uv run alembic upgrade head                     # 在项目根目录应用迁移
pre-commit install                              # 安装 git 提交钩子
```

## 项目结构

```text
.
├── pyproject.toml                # uv 项目配置与依赖
├── uv.lock                       # 锁定文件（提交到仓库以保证可复现）
├── .python-version               # 项目使用的 Python 版本
├── alembic.ini                   # Alembic 配置（迁移脚本位于 src/migrations）
├── Dockerfile                    # 应用容器镜像构建
├── docker-compose.yml            # 本地/测试环境编排
├── default.conf                  # Nginx 反向代理示例
├── .pre-commit-config.yaml       # 提交前检查
├── .gitattributes               # 统一 LF 换行、标记二进制文件
├── README.md                     # 本文档
│
├── src
│   ├── .env.example              # 环境变量示例（请复制为 .env）
│   ├── run.py                    # 本地开发启动脚本（可选）
│   ├── app
│   │   ├── main.py               # 应用入口
│   │   ├── api
│   │   │   ├── __init__.py       # /api 路由聚合
│   │   │   └── v1
│   │   │       └── __init__.py   # /api/v1 路由（含健康检查）
│   │   ├── logs/core             # 核心代码（历史目录名，见下方说明）
│   │   │   ├── config.py         # Pydantic Settings 配置
│   │   │   ├── setup.py          # FastAPI 应用工厂与生命周期
│   │   │   ├── logger.py         # 日志配置
│   │   │   ├── db
│   │   │   │   ├── database.py   # 异步引擎与会话
│   │   │   │   └── models.py     # 基础 Mixin（UUID / 时间戳 / 软删除）
│   │   │   ├── exceptions        # 业务异常
│   │   │   ├── utils             # cache / queue / rate_limit
│   │   │   └── worker            # ARQ worker 配置与后台任务
│   │   └── middleware
│   │       └── client_cache_middleware.py
│   └── migrations
│       ├── env.py                # Alembic 环境
│       └── versions              # 迁移版本
└── tests
    ├── conftest.py               # pytest fixtures
    └── test_*.py                 # 测试用例
```

> 说明：核心代码实际位于 `src/app/logs/core/`，`src/app/core/` 这个路径**并不存在**。
> `logs` 是历史遗留的目录名（同时是运行日志的落盘位置），因此 `.gitignore` 只忽略
> `src/app/logs/*.log`，而不能整目录忽略。

## 配置说明

配置集中在 [`src/app/logs/core/config.py`](src/app/logs/core/config.py)，通过 `pydantic-settings` 从 `src/.env` 读取。新增配置时请在该文件中补充对应的 Settings 类。

`ENVIRONMENT` 的行为：

- `local`：`/docs`、`/redoc`、`/openapi.json` 全部开放
- `staging`：接口文档开放（可在此基础上扩展超级用户鉴权）
- `production`：接口文档关闭

## 日志与连接观察

应用会在启动和关闭时打印数据库、Redis 缓存/队列/限流等连接信息，方便本地开发观察：

- 数据库引擎初始化（主机、端口、数据库名）
- Redis 缓存、队列、限流连接的建立与关闭
- `--skip-infra` 模式下会打印跳过的连接项
- 缓存命中/未命中、写入与失效（`DEBUG` 级别）
- 限流触发与计数（`WARNING` / `DEBUG` 级别）

日志同时输出到控制台和 `src/app/logs/app.log`。可通过 `.env` 调整：

```dotenv
LOG_LEVEL=INFO     # DEBUG / INFO / WARNING / ERROR
DB_ECHO=false      # true 时打印 SQLAlchemy 执行的 SQL
```

如需查看缓存、限流等调试日志，将 `LOG_LEVEL` 设置为 `DEBUG` 即可。

## 连接验证表

应用启动并成功连接 PostgreSQL 后，会自动在目标数据库中创建一张 `connection_test` 测试表，用于验证数据库连接与建表能力。

- 模型定义：`src/app/logs/core/db/models.py` 中的 `ConnectionTest`
- 创建时机：应用启动时的 `Base.metadata.create_all()`（使用 `--skip-infra` 时跳过）
- 成功标志：日志中会输出
  ```
  数据库表结构创建/校验完成，连接验证表 connection_test 已就绪
  ```

登录 PostgreSQL 后可用以下 SQL 验证：

```sql
SELECT * FROM connection_test;
```

如果不需要这张验证表，删除 `src/app/logs/core/db/models.py` 中的 `ConnectionTest` 模型即可。

## Milvus 向量数据库（可选）

模板内置了 Milvus 连接管理，默认**关闭**，未部署 Milvus 时不会发起连接，也不会报错。

### 配置

在 `src/.env` 中配置（`ENABLE_MILVUS` 默认 `false`）：

```dotenv
ENABLE_MILVUS=false          # 改为 true 启用 Milvus
AUTO_CREATE_RAG_COLLECTIONS=false  # 改为 true 可在启动时自动创建 RAG 集合与索引
MILVUS_HOST=localhost        # Milvus standalone 的 gRPC 地址
MILVUS_PORT=19530            # 对应 docker-compose 暴露的 19530 端口
# MILVUS_URI=http://localhost:19530   # 也可直接指定完整 URI，优先于 HOST/PORT
MILVUS_DB_NAME=default
```

### 使用方式

```python

from app.logs.core.utils import milvus

client = milvus.get_client()  # 未启用时返回 None
if client is not None:
    collections = client.list_collections()
```

应用启动/关闭时会根据 `ENABLE_MILVUS` 自动连接/断开（在 `setup.py` 的生命周期中管理）。

### 状态接口

启用后可通过接口查看连接状态：

```sh
curl http://127.0.0.1:8888/api/v1/milvus/status
```

返回：

```json
{ "enabled": true, "connected": true, "uri": "http://localhost:19530", "db_name": "default" }
```

### RAG 集合自动创建

启用 Milvus 且开启 `AUTO_CREATE_RAG_COLLECTIONS` 后，应用启动时会自动创建（幂等）两个与 PostgreSQL 表对应的向量集合：

| Milvus 集合 | 对应 PostgreSQL 表 | 主要字段与索引 |
| --- | --- | --- |
| `rag_documents` | `rag_documents` | `id`（INT64 主键）、`title`、`source_type`、`source_path`、`author`、`created_at`、`updated_at`、`metadata`；`source_type`、`created_at` 建立倒排索引 |
| `rag_chunks` | `rag_chunks` | `id`、`document_id`、`chunk_index`、`content`、`embedding`（1536 维，HNSW + COSINE）、`token_count`、`section_title`、`content_type`、`metadata`、`created_at`；`document_id`、`content_type`、`created_at` 建立倒排索引 |

集合定义位于 [`src/app/logs/core/utils/rag_collections.py`](src/app/logs/core/utils/rag_collections.py)，可通过
`rag_collections.ensure_collections(client)` 手动触发。集合已存在时不会重复创建，也不会覆盖已有数据。

该开关**默认关闭**，即默认不会在启动时自动创建集合。如需在启动时自动创建，在 `src/.env` 中设置：

```dotenv
AUTO_CREATE_RAG_COLLECTIONS=true
```

关闭（默认）或需要手动控制初始化时机时，可手动调用 `rag_collections.ensure_collections(client)` 完成集合与索引初始化。

## 数据库迁移

模板使用 Alembic 管理数据库结构：

```sh
uv run alembic revision --autogenerate -m "create users"
uv run alembic upgrade head
```

说明：

- 迁移命令必须在**项目根目录**执行；`src/migrations/env.py` 是 Alembic 内部的钩子脚本，请勿用 `python src/migrations/env.py` 直接运行。
- 新模型需要在 `src/app/logs/core/db/models.py` 中定义，并确保被 `Base.metadata` 收集，`autogenerate` 才能识别差异。
- 如需避免启动时自动建表，可在 `src/app/main.py` 中调用 `create_application(..., create_tables_on_start=False)`。

## 后台任务（ARQ）

Worker 示例位于 [`src/app/logs/core/worker/functions.py`](src/app/logs/core/worker/functions.py)，默认提供了 `sample_background_task`。

本地启动 worker：

```sh
uv run arq app.logs.core.worker.settings.WorkerSettings
```

在路由中入队任务：

```python
from arq import create_pool
from arq.connections import RedisSettings

from app.logs.core.config import settings

pool = await create_pool(RedisSettings(host=settings.REDIS_QUEUE_HOST, port=settings.REDIS_QUEUE_PORT))
job = await pool.enqueue_job("sample_background_task", "hello")
```

## 测试

测试使用 pytest、httpx 与 `TestClient`：

```sh
uv run python -m pytest
```

测试配置见 [`tests/conftest.py`](tests/conftest.py)。新增测试文件时以 `test_<entity>.py` 命名。

## 代码风格与检查

```sh
uv run ruff check --fix
uv run ruff format
uv run mypy src tests
```

> 说明：仓库当前的 `ruff`、`ruff format --check`、`mypy src tests`、`pytest` 均为全绿状态；新增代码请保持同一标准（细则见 AGENTS.md「编码规范」章节）。

提交前建议安装 pre-commit：

```sh
pre-commit install
```

## Docker 部署

```sh
docker compose up --build
```

生产环境建议：

- 将 `src/.env` 中的 `ENVIRONMENT` 改为 `production`
- 使用 gunicorn 管理 uvicorn worker（`Dockerfile` 中已给出注释示例）
- 需要反向代理时启用 `docker-compose.yml` 中的 `nginx` 服务与 `default.conf`

## 扩展指南

新增一个业务模块通常包含以下步骤：

1. 在 `src/app/logs/core/db/models.py` 中定义 SQLAlchemy 模型
2. 在 `src/app/api/v1/` 下新增路由模块，并在 `__init__.py` 中注册
3. 在 `src/app/logs/core/config.py` 中补充必要的配置
4. 生成并应用迁移
5. 在 `tests/` 下补充测试

## 许可

[MIT](LICENSE.md)
