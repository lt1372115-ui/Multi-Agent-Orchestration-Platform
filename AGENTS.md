# 仓库协作约定（Codex / AI Agent 使用）

本文档面向在本仓库中工作的 AI 编码代理。所有对话、注释与文档均使用**简体中文**。

## 项目概览

- 这是一个基于 **FastAPI + SQLAlchemy + Pydantic v2** 的异步 API 模板。
- 依赖由 **uv** 管理，配置见 `pyproject.toml`，锁定文件为 `uv.lock`，Python 版本记录在 `.python-version`。
- 应用入口为 `src/app/main.py`，路由前缀为 `/api/v1/`。

## 常用命令

```sh
uv sync                                        # 安装/同步依赖
uv run python src/run.py                       # 本地启动 API（默认 8888 端口）
uv run python src/run.py --skip-infra           # 无 Postgres/Redis 时快速启动
uv run python -m pytest                        # 运行测试
uv run ruff check --fix && uv run ruff format  # 修复并格式化代码
uv run mypy src                                # 类型检查
uv run alembic revision --autogenerate -m "..." # 在项目根目录生成迁移
uv run alembic upgrade head                     # 在项目根目录应用迁移
pre-commit install                              # 安装 git 提交钩子
```

## 目录结构与分层

- `src/app/api/v1/`：版本化路由，按业务模块拆分并在此注册。
- `src/app/logs/core/`：配置、日志、数据库、异常、工具与 worker。
  - `core/config.py`：所有 Pydantic 配置集中于此。
  - `core/db/database.py`：异步引擎与 `async_get_db` 依赖。
  - `core/db/models.py`：ORM 基础 Mixin；业务模型也应维护在 `db` 目录下。
- `src/app/middleware/`：Starlette 中间件。
- `src/migrations/`：Alembic 迁移（配置文件 `alembic.ini` 位于项目根目录）。
- `tests/`：pytest 测试；`tests/conftest.py` 提供 `client`、`db` 等 fixtures。

> 注意：`src/migrations/env.py` 是 Alembic 的内部钩子，不要直接执行 `python src/migrations/env.py`。
> 迁移必须通过 `uv run alembic ...` 命令在项目根目录运行。

## 编码规范

以下约定**全部由工具强制**，提交前必须三条命令全绿：

```sh
uv run ruff check --fix && uv run ruff format   # 静态检查 + 格式化
uv run mypy src tests                           # 类型检查（含测试）
uv run python -m pytest                         # 测试
```

### 排版

- 行宽 120、缩进 4 空格、目标 Python 3.13。
- 文本文件一律使用 **LF** 换行：由 `.gitattributes` 与 `[tool.ruff.format] line-ending = "lf"` 双向锁定。
- Ruff 规则集见 `pyproject.toml`：除 pycodestyle/pyflakes 外还启用命名（`N`）、内置名遮蔽（`A`）、类型标注（`ANN`）、异步正确性（`ASYNC`）、时区（`DTZ`）、pathlib（`PTH`）、FastAPI 用法（`FAST`）、导入风格（`TID`/`I`）、日志（`LOG`）、pytest 风格（`PT`）等。
- mypy 开启 `warn_return_any`、`warn_unused_ignores`、`warn_redundant_casts`、`strict_equality`，并对 `app.*` / `mcp_servers.*` / `tests.*` 强制函数签名标注。
- 禁止裸 `# noqa` 与裸 `# type: ignore`，必须写明具体规则码（`PGH003` / `PGH004`）。

### 命名与结构

- 文件、函数、变量用 `snake_case`，类用 `PascalCase`，模块级常量用 `UPPER_SNAKE_CASE`，数据库列用 `snake_case`。
- 禁止遮蔽内置名（如 `id`、`type`、`list`）。
- 源码目录必须带 `__init__.py`，不使用隐式命名空间包。
- 路由统一以 `/api/v1/` 为前缀；测试文件命名为 `test_<entity>.py`。

### 导入

- 一律使用**绝对导入**（`from app.logs.core.config import settings`），禁止 `from ....config import ...` 这类相对层级写法。
- 导入分三组：标准库 → 第三方 → 第一方（`app` / `mcp_servers` / `tests`），由 Ruff 自动排序。

### 类型与文档

- 公共模块、类、函数必须写**中文** docstring；参数或行为不直观时补 `Args:` / `Raises:` 段落。
- 所有函数（含测试）都要标注参数与返回值；不追求消灭 `Any`，但 `Any` 只能出现在第三方边界或图状态等确实无法收窄处。
- 不留无效的 `# type: ignore`：`warn_unused_ignores` 会直接报错。

### 运行时写法

- 时间：禁止无时区 `datetime.now()`；存库用 UTC，对外展示用 `datetime.now(UTC).astimezone()`。
- 路径：使用 `pathlib.Path`，不再用 `os.path`。
- 日志：模块级 `logger = logging.getLogger(__name__)`；禁止在 root logger 上直接 `logging.info(...)`，禁止用 f-string 拼日志（用 `%s` 占位）。
- 异常：抛具体异常类型（如 `RuntimeError`），不要 `raise Exception(...)`；对外的业务失败使用 `app.logs.core.exceptions` 中的异常。
- 不要用 `assert` 做业务校验（`python -O` 会移除 assert）。
- FastAPI：查询参数与依赖用 `Annotated[...]` 形式；返回类型已标注时不要再写冗余的 `response_model=`。
- 智能体、工具、长生命周期客户端沿用「模块级单例 + 懒加载」模式（见 `src/app/logs/core/agents/`）。

## 新增模块的步骤

1. 在 `src/app/logs/core/db/models.py` 中定义 SQLAlchemy 模型。
2. 在 `src/app/api/v1/` 下新增路由文件，并在 `__init__.py` 中 `include_router`。
3. 在 `src/app/logs/core/config.py` 中补充需要的配置项。
4. 生成迁移：`uv run alembic revision --autogenerate -m "..."`，并执行 `uv run alembic upgrade head`。
5. 在 `tests/` 下同步补充测试，并确保 `uv run python -m pytest` 全部通过。

## 配置与安全

- 环境变量放在 `src/.env`（参考 `src/.env.example`），**不要提交真实密钥**。
- `SECRET_KEY` 等敏感配置必须使用安全随机值。
- 修改 `src/.env.example` 与 `src/app/logs/core/config.py` 时保持二者同步。

## 提交与 Pull Request

- 分支命名使用 `feature/xxx` 或 `fix/xxx`。
- 提交信息简洁描述改动，例如 `Add user endpoint`。
- PR 说明改动目的，必要时更新 `README.md`。
- 确保 pre-commit、测试与类型检查全部通过后再提交。
