# FastAPI 后端开发模板（中文说明）

本文件是 [`README.md`](README.md) 的中文版。完整、最新的说明请以 `README.md` 为准。

## 项目简介

这是一个基于 **FastAPI + SQLAlchemy + Pydantic v2** 的异步后端模板，使用 **uv** 管理依赖，开箱即用。

内置能力包括：分层目录、配置管理、异步数据库会话、Redis 缓存/队列/限流、ARQ 后台任务、客户端缓存中间件、日志、健康检查、Docker 编排，以及 pytest / ruff / mypy / pre-commit 工具链。

## 快速开始

```sh
# 1. 安装 uv（详见 README.md「安装 uv」）
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 进入项目并安装依赖
cd FastAPi_Template
uv sync

# 3. 配置环境变量
cp src/.env.example src/.env

# 4. 启动依赖服务（可选，仅需预览接口时可跳过）
docker run -d --name postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
docker run -d --name redis -p 6379:6379 redis:alpine

# 5. 启动服务（默认 8888 端口）
uv run python src/run.py
# 无 Postgres/Redis 时：
uv run python src/run.py --skip-infra
```

打开 http://127.0.0.1:8888/docs 查看接口文档。

## 常用命令

```sh
uv sync                                        # 安装/同步依赖
uv run python src/run.py                       # 本地启动（8888）
uv run python src/run.py --skip-infra           # 跳过外部依赖启动
uv run python -m pytest                        # 测试
uv run ruff check --fix && uv run ruff format  # 代码检查与格式化
uv run mypy src                                # 类型检查
uv run alembic revision --autogenerate -m "..." # 生成迁移
uv run alembic upgrade head                     # 应用迁移
```

## 项目结构

- `src/app/api/v1/`：API 路由
- `src/app/logs/core/`：配置、日志、数据库、工具、worker
- `src/app/middleware/`：中间件
- `src/migrations/`：Alembic 迁移
- `tests/`：pytest 测试
- `src/scripts/`：初始化脚本（含占位脚本）

详细说明请参阅 [README.md](README.md)。
