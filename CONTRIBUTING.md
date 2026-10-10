# 贡献指南

感谢你对 **FastAPI Template** 的关注！无论是报告 Bug、改进文档，还是提交代码，我们都非常欢迎。

## 准备开发环境

### 克隆仓库

1. **Fork 仓库**：在目标平台（如 Gitee / GitHub）上 Fork 本项目。
2. **创建分支**：基于最新主分支创建特性分支：

   ```sh
   git checkout -b feature/fooBar
   ```

3. **安装依赖**：本项目使用 [uv](https://docs.astral.sh/uv/) 管理依赖，请先安装 uv（安装方式见 `README.md` 的「安装 uv」章节）。

   ```sh
   uv sync
   ```

## 开发与验证

### 启动服务

```sh
uv run python src/run.py
```

### 运行测试

```sh
uv run python -m pytest
```

### 代码风格与静态检查

```sh
uv run ruff check --fix
uv run ruff format
uv run mypy src tests
```

### 提交前检查

建议安装 pre-commit，在提交时自动执行检查：

```sh
uv run pre-commit install
```

## 编码规范

完整且可执行的规范见仓库根目录的 [`AGENTS.md`](AGENTS.md)「编码规范」章节，要点如下：

- 行宽 120、缩进 4 空格、文本文件统一 LF 换行；由 Ruff 与 `.gitattributes` 强制。
- 命名：文件/函数/变量 `snake_case`，类 `PascalCase`，模块级常量 `UPPER_SNAKE_CASE`，数据库列 `snake_case`。
- 导入：一律绝对导入，禁止相对层级导入；导入分组由 Ruff 自动排序。
- 类型：所有函数（含测试）标注参数与返回值；不留无效的 `# type: ignore`。
- 文档：公共模块、类、函数写中文 docstring。
- 时间用 `datetime.now(UTC)` 系列（禁止无时区 `now()`）；路径用 `pathlib`；日志用模块级 `logger` + `%s` 占位。
- 路由统一以 `/api/v1/` 为前缀；测试文件命名为 `test_<entity>.py`，新增功能同步补充测试。

> 提交前请确保以下三条命令全部通过，pre-commit 钩子也会执行它们：
>
> ```sh
> uv run ruff check --fix && uv run ruff format
> uv run mypy src tests
> uv run python -m pytest
> ```

## 提交 Pull Request

1. 将改动推送到你的 Fork 分支：

   ```sh
   git push origin feature/fooBar
   ```

2. 打开 Pull Request，说明改动目的，关联相关 issue。
3. 必要时更新 `README.md`。
4. 确保测试与静态检查全部通过。

## 其他约定

- 保持与上游仓库同步，避免合并冲突。
- 遵循仓库根目录的 `AGENTS.md` 与 `CODE_OF_CONDUCT.md`。

感谢你的贡献！🚀
