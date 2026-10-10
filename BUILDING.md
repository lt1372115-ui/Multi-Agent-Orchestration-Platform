# BUILDING · 项目搭建全过程记录

> 本文档按时间顺序记录本项目从 0 到当前状态的每一步：**规划（要解决什么）→ 怎么做（方案与操作）→ 做了什么（改动明细）→ 成果总结（验证结果）**。
>
> 说明：
> - 项目未初始化 git，无提交历史可回溯；前 3 个阶段（模板基线、环境准备）依据 README 与仓库现状还原。
> - 2026-09-21 起各阶段均有会话记录可核，操作命令在对应阶段给出。

---

## 阶段 0 · 模板基线：基于 FastAPI 模板开箱即用

**规划**：以 `fastapi-template`（FastAPI + SQLAlchemy + Pydantic v2，uv 管理依赖）为底座起步，先确认模板已内置的能力，再在其上叠加业务。

**怎么做**：克隆模板 → `uv sync` 安装依赖（128 个包）→ `cp src/.env.example src/.env` → 启动验证。

**做了什么**：确认模板自带以下开箱即用能力（见 README）：

- 全异步：FastAPI + SQLAlchemy 异步引擎 + asyncpg
- 分层目录：`src/app/api / core / db / middleware`
- Redis 缓存/队列/限流、ARQ 后台任务、客户端缓存中间件
- 基于环境的 API 文档开关（local / staging / production）
- Dockerfile + docker-compose（web / worker / db / redis）
- pytest / ruff / mypy / pre-commit 工具链

**成果总结**：模板基线可用，`uv run python src/run.py --skip-infra` 可正常启动并监听 8888 端口。

---

## 阶段 1 · 2026-09-21：项目通读、清理与前端链路验证

### 1.1 项目通读与概述

**规划**：新环境首次接触项目，先全面了解技术栈、链路结构与核心组成。

**怎么做**：通读全项目代码与配置。

**做了什么**：整理出项目四大部分——浏览器前端、后端路由、智能体、和风天气客户端；后端 4 个接口，其中 `/chat` 为 SSE 流式 Agent 问答；智能体使用 `langchain.agents.create_agent` + DeepSeek，封装实时天气与每日预报两个工具。

**成果总结**：发现高风险项——`.env.example` 疑似含真实和风天气私钥（随后清理），测试覆盖偏薄。

### 1.2 基础清理

**规划**：删除无用文件、完善忽略规则。

**怎么做**：定位空目录与 .gitignore 缺口。

**做了什么**：

- 删除根目录空目录「新建文件夹」。
- `.gitignore` 新增 `src/app/logs/`（原 `*.log` 只能匹配 `app.log`，无法忽略滚动备份文件）。
- 依据 DEPLOY.md 校准 `.dockerignore`：保留 Dockerfile 用到的 `pyproject.toml / uv.lock / .python-version / src/`；忽略 `.venv / __pycache__ / .uv-cache`、含密钥的 `src/.env / src/.env.example`、`tests / storage / src/app/logs` 等非运行必需项。

**成果总结**：仓库干净，镜像构建上下文瘦身、密钥不外泄。

### 1.3 智能体调用链路：核查已实现并出说明文档

**规划**：需求为「前端查询时展示智能体调用的工具与调用链路」，先核对代码库是否已实现。

**怎么做**：分析后端 `agent.py` 与前端 `app.js`，对照需求。

**做了什么**：确认功能已实现——

- 后端 `agent.py` 已重构出事件翻译器，产出 `step / content / done` 协议，含 `_tool_label / _summarize / _preview_limit` 等字段。
- 前端 `app.js` 已实现 trace/steps 渲染、状态着色、耗时展示、原始返回展开。
- 创建《智能体调用链路展示-改动说明.md》完整记录该能力。

**成果总结**：需求已满足，无需重复改码；后续排查「只显示查询中」时确认是缓存问题。

### 1.4 排查「前端只显示查询中」

**规划**：现象为提问后只显示「查询中」，链路不出现。

**怎么做**：逐层验证——curl 测 `/chat` 路由、测天气接口、检查静态资源版本、通读前后端逻辑。

**做了什么**：

- 确认后端 `agent.py` 能完整输出 `step / tool / summary / preview / content / done`；HTTP 路由与天气接口均正常。
- 根因：**浏览器缓存了旧版 `app.js`**（旧版只发 `type:"tool"` 消息，新版前端收到会静默跳过）；且早期后端进程跑的是旧版 `agent.py`（发旧协议）。
- 解决：无痕窗口 / `Ctrl+Shift+R` 强制刷新，静态资源升版到 `?v=2`，重启后端。

**成果总结**：链路功能确认无误，问题在加载层缓存，已解决。

### 1.5 本地启动与部署演练

**规划**：本地与云服务器都能跑起来。

**怎么做**：本地 `uv sync` + `uv run python src/run.py --skip-infra`；服务器端给出裸机（systemd）与 Docker 两套方案。

**做了什么**：

- 本地：uv sync 安装 128 个包成功，应用启动监听 8888，Redis/Postgres 按 `--skip-infra` 跳过。
- 服务器：因云环境已有 Postgres/Redis，推荐裸机部署；Docker 方案下指出 `.env` 中 DB/REDIS 主机需用 `127.0.0.1`（VPC 内访问公网 IP 会失败），阿里云安全组需放行端口，国内拉镜像需配加速器。

**成果总结**：本地全链路可跑；给出可复用的部署步骤，后续沉淀进 DEPLOY.md。

---

## 阶段 2 · 2026-09-22：全面审查与致命问题修复

### 2.1 项目全面审查

**规划**：对天气 Agent 项目做一次完整审查，定位启动崩溃与隐患。

**怎么做**：静态通读 + 启动验证。

**做了什么**（发现的问题清单）：

- **致命**：`server.py` 残留挂载代码导致 `NameError`；`main.py` 中 `task_mcp` 未定义 → 应用无法启动。
- `conftest.py` 因导入 `main.py` 受启动问题牵连。
- `dingtalk.py` 存在未导入依赖与路由注册错误。
- 任务 MCP 建表方式绕过 Alembic 迁移体系。
- DeepSeek 存在两套功能重叠的实现。
- README 与 `.env.example` 与实际项目脱节。

**成果总结**：输出问题报告与修复优先级建议，为后续阶段提供路线图。

### 2.2 钉钉消息发送通道修复

**规划**：钉钉发不出消息。

**怎么做**：分析根因、更换 CLI 发送通道。

**做了什么**：

- 根因：收件人**重名**；`dws chat +dm --to` 只接受姓名/花名，无稳定 ID 传参方式，重名时返回 `ambiguity` 错误。
- 改为 `dws chat +messages-send --as user`，支持 `--user-query` 与 `--open-dingtalk-id`，用 ID 精确定位。
- 新增错误翻译函数处理结构化错误（错误信息在 stderr）；接口升级为姓名/ID 二选一；同步 Agent 工具参数；前端控制台增加输入框。

**成果总结**：消息发送问题修复，测试全部通过。

---

## 阶段 3 · 2026-09-23：启动崩溃（模型重复定义）修复

**规划**：应用启动即崩溃，报 `InvalidRequestError: Table 'connection_test' is already defined`。

**怎么做**：检查 `src/app/core/db/models.py`，定位重复定义。

**做了什么**：

- 根因：同一文件存在两段独立的旧版/新版 `ConnectionTest` 定义，`__tablename__ = "connection_test"` 声明了两次。
- 删除前 1-59 行旧版冗余定义（UUIDMixin 风格），保留新版 `MappedAsDataclass` 风格 + `IDMixin` 自增主键。
- 旧版 `UUIDMixin` 无外部引用，安全移除。

**成果总结**：`uv run python -c "from src.app.main import app"` 输出 `IMPORT OK`，启动崩溃修复。

---

## 阶段 4 · 2026-09-26：全仓库统一为绝对导入

**规划**：IDE 中看到的「绝对导入 + 缺 products 挂载」与磁盘实际不一致；用户拍板：**统一改成 `app.` 绝对导入**（含运行入口与所有模块的 import 方式）。

**怎么做**（关键决策）：

- 项目是 **src 布局**：顶层包是 `src.app`，运行时入口为 `app.main:app`；`import app` 需 `src` 在 `sys.path` 上。
- 因此运行入口类配置必须联动：`run.py` 把 `src`（而非项目根）加入 `sys.path`，`PYTHONPATH` 指向 `/app/src`。
- `mcp_servers` 是 `app` 的兄弟目录，用 `mcp_servers.xxx` 导入。

**做了什么**：

- 源码（约 30 个文件）：`src.app.*` / 相对导入 → `app.*`；`mcp_servers/qweather_mcp`、`task_mcp` → `mcp_servers.*`；tests 同步。
- 运行入口/配置：`run.py`（`uvicorn app.main:app` + 插入 `src`）、`alembic.ini`（`prepend_sys_path = src`）、`pyproject.toml`（pytest `pythonpath = ["src"]`）、`Dockerfile`（`PYTHONPATH=/app/src` + `uvicorn app.main:app`）、`docker-compose.yml`（web/worker 命令）。
- 文档：README.md、DEPLOY.md 全部 `src.app.` → `app.`。
- 修复 `src/app/core/agents/ecommerce/product/base.py` 残留相对导入。

**成果总结**：

- `from app.main import app` → `IMPORT OK`。
- `pytest tests/test_health.py tests/test_agent_events.py` → **9 passed**。
- OpenAPI 五类路由全部注册：`/api/v1/auth/*`、`/api/v1/products`、`/api/v1/dingtalk/*`、`/api/v1/milvus/status`、`/api/v1/qweather/*`。

**遗留**：`task_mcp/server.py` 5 处 FastMCP `Depends` 写法触发 ruff B008 误报（框架惯用法，与本次改动无关）。

---

## 阶段 5 · 2026-09-26：电商导购智能体短期记忆

**规划**：依据《电商导购智能体》设计文档落地「短期记忆」两步：① 状态载体 `AgentState`；② 窗口管理策略。文档明确 summary / hybrid 策略**暂不实现**（需配合长期记忆）。

### 5.1 短期记忆载体 AgentState（文档第一步）

**规划**：短期记忆的唯一载体 = LangGraph 共享状态字典。

**怎么做**：按文档定义 `TypedDict` + `add_messages` reducer。

**做了什么**：新增 `src/app/core/agents/ecommerce/state.py`：

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]  # 短期记忆载体
    user_id: int
```

- `add_messages`：追加不覆盖、按 id 去重、支持 `RemoveMessage` 删除、自动归一为 `BaseMessage`。
- 无 reducer 的字段（`user_id`）走默认「覆盖」语义。

**成果总结**：短期记忆载体就绪；`total=False` 保证所有键可选。

### 5.2 窗口管理模块修复与补全（文档第二步）

**规划**：控制注入大模型的对话历史长度，防上下文撑爆与 token 成本失控。

**怎么做**：核查既有 `window.py` / `runtime.py`，发现两处硬伤 + 一处结构问题，逐一修复。

**做了什么**：

- [window.py](src/app/logs/core/agents/window.py)：
  - 修复坏导入 `from ...config import settings`（解析到不存在的 `app.config`，导入即 `ModuleNotFoundError`）→ `from app.core.config import settings`。
  - `build_window_strategy` 被缩进错误地写进 `TokenBudgetWindowStrategy` 类内部 → 挪回模块级函数。
  - 移除为 summary 预留的未使用导入（`ChatOpenAI / SecretStr / Any`），通过 ruff F401。
  - 保留文档要求的辅助函数：`_message_text / _role_label / _is_cjk / _estimate_tokens / _slice_by_tokens / _truncate_tool_outputs / _remove_messages` 与 `_SUMMARY_PROMPT`。
- [runtime.py](src/app/logs/core/agents/runtime.py)：原是残缺片段（缺 import、缺 `_window` 全局）→ 补全为 `get_window_strategy()` 单例（懒加载，按 `ECOMMERCE_WINDOW_STRATEGY` 切换）。
- 策略实现：`TruncateWindowStrategy`（保留最近 N 条）、`TokenBudgetWindowStrategy`（按 token 预算从尾部保留）；**summary / hybrid 按文档暂不实现**，`build_window_strategy` 对未知策略回退 truncate。

### 5.3 连带修复：base.py 的 settings 导入

**规划**：上一轮 `ruff --fix` 把 `settings` 误判 F401 删掉，导致 `build_product_source` 出现 F821。

**怎么做**：恢复导入并统一为绝对风格。

**做了什么**：[base.py](src/app/logs/core/agents/ecommerce/product/base.py) 恢复 `from app.core.config import settings`；函数内懒加载 `from .pgvector` 等改为 `app.*` 绝对导入；补齐类后空行。

**成果总结**：

- 全链路导入 OK（`app.main`、`build_product_source`、`AgentState`、`get_window_strategy`）。
- 策略行为实测：truncate 25 条保留最近 20、compact 产出 5 条 `RemoveMessage`；token 按预算从尾部保留且始终含最新消息。
- ruff：本次涉及文件全部通过；测试 9 passed。

---

## 阶段 6 · 2026-09-26：建立本 BUILDING 文档

**规划**：沉淀项目从 0 搭建的每一步（规划 / 怎么做 / 做了什么 / 成果总结），便于回溯与交接。

**怎么做**：汇总记忆记录（2026-09-21 起各会话）、README 基线、仓库现状，按时间线还原各阶段。

**做了什么**：创建本文档。

**成果总结**：项目历程文档化；后续新阶段在此追加。

---

## 阶段 7 · 2026-10-08：A2A 协议官方化 + 编排器短期记忆

**规划**：依据飞书「第四章 · A2A 协议」文档（Ed4wwoeEWiCuR7k3f0cc7B4LnAf）更新 A2A 层并丰富其余代码——从「手写 A2A API」迁移到官方 `a2a-sdk`，并为多智能体编排器补齐短期记忆与确认门禁。

**怎么做**（关键决策）：

- 引入官方 SDK：`uv add "a2a-sdk[fastapi,sqlite]"`（版本 1.2.2，连带 aiosqlite）。
- 删除旧手写实现：`a2a/models.py`、`a2a/remote.py`，全面改用 SDK 的 `types / DefaultRequestHandler / add_a2a_routes_to_fastapi / AgentExecutor / TaskUpdater`。
- 任务事件顺序必须「先 enqueue 初始 Task，再做状态更新」，否则 SDK 抛错。
- 流式 artifact 经 `artifact_update` payload 传输，客户端 `stream()` 必须处理该分支。
- FastMCP `combine_lifespans` 要求所有 lifespan 是 async 上下文管理器工厂（`a2a_lifespan` 加 `@asynccontextmanager`）。

**做了什么**：

- `a2a/executor.py`（重写）：`SubAgentExecutor(AgentExecutor)`，SUBMITTED →（INPUT_REQUIRED | start_work → add_artifact → complete），异常走 `failed`。
- `a2a/server.py`（重写）：`build_agent_card / build_task_store(memory|sqlite|postgres) / build_agent_a2a_app / build_a2a_mounts / a2a_lifespan`。
- `a2a/client.py`（重写）：`A2ASubAgent`（httpx 连接池 + 退避重试 + 确认闭环 `confirm()`）。
- `a2a/__init__.py`（重写）：导出以上新 API。
- `main.py`：`build_a2a_mounts` 把 qweather / dingtalk / ecommerce 挂到 `/a2a/{name}`，合并 `a2a_lifespan`。
- 编排器短期记忆：为 `engine.py` 挂 `get_checkpointer`（按 `user_id:conversation_id` 即 thread_id 隔离），支持同会话多轮累积历史。
- 确认门禁：`protocol.BaseSubAgent` 增 `confirmation_required / confirmation_prompt / needs_confirmation`（钉钉置 True）；`engine.tools_node` 抛 `ConfirmationRequired`；`orchestrator/confirmation.py` 提供 `store_pending / pop_pending`；`api/v1/orchestrator.py` 增 `POST /orchestrator/confirm`；前端 `orchestrator.html` 增确认/取消按钮。
- 配置：`config.py` 增 `OrchestratorSettings`（`ORCHESTRATOR_SUBAGENT_TRANSPORT: inprocess|a2a`）与 `A2ASettings`（`A2A_PUBLIC_BASE_URL / A2A_TASK_STORE / A2A_POSTGRES_URL / A2A_CLIENT_*`，含公网地址校验），并同步 `src/.env.example`。
- 测试：新增 `tests/test_a2a.py` 4 例（名片发现 / 流式 artifact / 确认 input-required→completed / 失败兜底不抛出）；`tests/test_orchestrator.py` 补确认门禁用例。

**成果总结**：

- A2A 层三个子智能体名片端点（`/a2a/*/.well-known/agent-card.json`）均返回 200。
- 全量 pytest **44 passed**；ruff（可修复项）已清理，剩余 6 处为项目既知 B008 FastMCP `Depends` 误报；本次改动文件 mypy clean。

**遗留**：`src/app/logs/core/agents/ecommerce/graph.py` 等原有文件的 `Returning Any` 类型告警与本次改动无关，未处理。

---

## 附：代码分层详解

> 请求从浏览器/外部客户端进来后的完整路径：
> `static 前端页 / API 请求 → FastAPI(main.py) → middleware → api 路由 → core 业务/数据层 → 外部服务(Postgres/Redis/Milvus/和风/DWS/DeepSeek)`
> 另有两个 MCP Server 挂载在 `/qweather_mcp`、`/task-mcp`，走 Streamable HTTP 协议。

### 第 1 层 · 应用入口 `src/app/main.py`

**职责**：组装 FastAPI 应用、挂载两个 MCP Server、合并生命周期。

```python
app = create_application(router=router, settings=settings)   # 由 setup.py 工厂创建
qweather_app = qweather_mcp.http_app(path="/", transport="streamable-http")
task_app = taskmcp.http_app(path="/", transport="streamable-http")
app.router.lifespan_context = combine_lifespans(app.router.lifespan_context, qweather_app.lifespan, task_app.lifespan)
app.mount("/qweather_mcp", qweather_app)
app.mount("/task-mcp", task_app)
```

**解析**：
- `create_application` 是应用工厂，路由与配置以参数注入（便于测试替换）。
- FastMCP 的 `http_app()` 把 MCP Server 包装成 ASGI 应用，`transport="streamable-http"` 启用新版流式 HTTP 传输。
- `combine_lifespans` 把主应用与两个 MCP 的启动/关闭钩子合并，保证 MCP 内部资源（如任务连接池）随应用启停。
- `mount` 让 FastAPI 把 `/qweather_mcp`、`/task-mcp` 前缀的请求转发给 MCP 应用。

### 第 2 层 · 路由层 `src/app/api/`

**职责**：HTTP 出入口。`api/__init__.py` 引入 `v1` 路由 → `v1/__init__.py` 聚合五个子模块并挂到 `/api/v1`。

| 文件 | 前缀 | 核心接口 | 解析要点 |
| --- | --- | --- | --- |
| `v1/__init__.py` | `/v1` | `GET /health` | 存活探针；`include_router` 聚合 5 个子路由 |
| `auth.py` | `/auth` | `POST /register` `/login` | 密码 `hash_password` 哈希落库；登录 `verify_password` 校验，签发 JWT；重名返回 409，密码错返回 401 |
| `products.py` | `/products` | 商品 CRUD | 完整增删改查 + 品类过滤 + 分页；`ProductResponse` 用 `from_attributes` 直接 `model_validate(ORM)`；`embedding` 字段仅入参、响应剔除避免返回过大向量；PATCH 用 `model_dump(exclude_unset=True)` 只更新提交字段 |
| `qweather.py` | `/qweather` | `GET /weather/now` `/weather/10d` `/travel-advice`，`POST /chat` | 城市名先 `lookup_city` 转经纬度再查天气；`/chat` 是 SSE 流式问答，见下方详解 |
| `dingtalk.py` | `/dingtalk` | `GET /health` `/auth/status` `/auth/login`、直连读写接口 | 所有操作经 `dingtalk_cli.run_dws` 白名单执行；`_as_http` 把 CLI 错误映射为状态码（未安装→503、写被禁→403、其他→502）；写操作受 `DINGTALK_ENABLE_WRITE` + 请求体 `confirm` 双控 |
| `milvus.py` | `/milvus` | `GET /status` | 透传 `milvus.status()`，未启用时返回 disabled |

**qweather `/chat` 的 SSE 协议**（前端链路渲染的数据契约）：
```
data: {"type": "step", "phase": "start", "kind": "model|tool", "id": ..., ...}
data: {"type": "step", "phase": "end", "status": ..., "elapsed_ms": ..., "summary": ..., "preview": ...}
data: {"type": "content", "content": "..."}
data: {"type": "error", "message": "..."}
data: {"type": "done", "elapsed_ms": ..., "path": [...]}
```
- `event_stream` 生成器把 agent 事件逐个 `json.dumps` 成 `data: ` 帧；流中途异常改为下发 `error` 事件，未收到 `done` 则补发终止标记，保证前端总能收尾。
- 响应头 `Cache-Control: no-cache` + `X-Accel-Buffering: no` 关掉 Nginx 缓冲，实现逐字输出。

### 第 3 层 · 核心层 `src/app/core/`

#### 3.1 配置 `config.py` —— 组合式 Settings

**解析**：核心是「多继承组合 + 全局单例」。

```python
class Settings(AppSettings, LoggingSettings, ..., ECommerceSettings, PostgresSettings, ...):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore", ...)

settings = Settings()   # 模块级单例，全项目共用一份
```

- 每个领域一个小 Settings 类（`DeepSeekSettings`、`MilvusSettings`、`QWeatherJwtSettings`、`ECommerceSettings` 等），`Settings` 多继承全部拼装 → 配置集中、按域分组、职责清晰。
- `BaseAppSettings` 统一 `env_file=src/.env`、`case_sensitive=False`；`extra="ignore"` 容忍 .env 里多余的键。
- `setup.py` 靠 `isinstance(settings, XxxSettings)` 判断启用哪些组件（建表 / Redis / Milvus / 文档），而不是写死开关——新增能力只需加一个 Settings 类。
- 环境开关 `ENVIRONMENT`（local / staging / production）控制 `/docs` `/redoc` `/openapi.json` 是否开放。

#### 3.2 应用工厂与生命周期 `setup.py`

**解析**：`create_application(router, settings)` 做四件事：
1. **按 Settings 类型补应用元信息**：`AppSettings` → title/description/contact；`EnvironmentSettings` → 生产环境关闭文档。
2. **生命周期 `lifespan_factory`**（启动/关闭钩子）：
   - `set_threadpool_tokens(100)` 调大 anyio 线程池，避免文件/Milvus 等阻塞调用饿死异步循环。
   - 建表：`Base.metadata.create_all`（`SKIP_INFRA_ON_START` 时跳过）。
   - 按 Settings 类型连接 Redis 缓存 / 队列 / 限流（`cache.pool`、`queue.pool`、`rate_limit.client` 挂到 `core/utils` 模块级变量上，全局共享）。
   - Milvus：`ENABLE_MILVUS` 时 `milvus.connect`，`AUTO_CREATE_RAG_COLLECTIONS` 时 `ensure_collections` 建 RAG 集合；关闭时逆序断开。
3. **静态页面托管**：`/` 返回 `static/index.html`（出行简报首页），`/dingtalk`、`/dingtalk/console` 返回钉协助手页面；`_static_version` 用静态目录最新文件的 mtime 自动生成 `?v=` 版本号，前端改动即换版本、杜绝浏览器缓存旧脚本。
4. **中间件与文档路由**：`ClientSideCacheSettings` 时挂 `ClientCacheMiddleware`；非生产环境挂 `/docs` `/redoc` `/openapi.json` 路由。

#### 3.3 安全 `security.py` 与 DeepSeek `deepseek.py`

- `security.py`：`hash_password`/`verify_password`（密码哈希）、`create_access_token`（JWT 签发，`SECRET_KEY` + `ALGORITHM=HS256`）。auth 路由依赖它。
- `deepseek.py`：`stream_chat(messages)` 以 async generator 流式调用 DeepSeek（`DEEPSEEK_API_KEY/MODEL/BASE_URL`），供 `travel-advice` 与智能体共用。

#### 3.4 数据库层 `core/db/`

**`database.py`（引擎与会话）**：

```python
class Base(DeclarativeBase, MappedAsDataclass): ...   # 声明基类，供所有模型继承
DATABASE_URL = f"{POSTGRES_ASYNC_PREFIX}{POSTGRES_URI}"   # postgresql+asyncpg://...
async_engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600, ...)
local_session = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
async def async_get_db(): ...   # 请求级会话依赖
```

- `pool_pre_ping`：每次取连接先探活，避免复用被服务端回收的空闲连接；`pool_recycle=3600` 连接满 1 小时回收，降低被防火墙断连概率。
- `MappedAsDataclass`：模型同时是 dataclass，字段用 `kw_only=True` 的映射列声明（见 models）。
- `local_session`：会话工厂；业务代码统一 `async with local_session() as session:`，`expire_on_commit=False` 让 commit 后仍可读属性。

**`models.py`（ORM 模型）**：

- **Mixin 复用**：`IDMixin`（BIGINT `Identity()` 自增主键）、`TimestampMixin`（`created_at/updated_at`，DB 默认 `current_timestamp(0)`）、`SoftDeleteMixin`（`deleted_at/is_deleted` 软删）。
- **`Vector` 适配器**：pgvector 类型在 asyncpg 下无编解码器，`bind_processor` 把 Python list 转成 `"[1.0,2.0]"` 文本再绑定（`cache_ok=True` 允许 SQLAlchemy 缓存编译）。
- **业务模型**：`ConnectionTest`（启动连接验证表）、`User`（认证主体，`username` 唯一索引，电商记忆归属到用户）、`Product`（商品库，含 `embedding` 向量列供 RAG 检索）、任务 MCP 相关模型。
- 此前阶段 3 修复的重复 `ConnectionTest` 定义即在此文件，现仅保留 `MappedAsDataclass` 风格单份定义。

#### 3.5 工具层 `core/utils/`

| 模块 | 职责 | 解析 |
| --- | --- | --- |
| `cache.py` | Redis 缓存 | 模块级 `pool/client` 由 setup.py 生命周期注入；缓存装饰器 + 客户端缓存工具 |
| `queue.py` | ARQ 任务队列 | `pool` 由生命周期注入，worker 消费 |
| `rate_limit.py` | 限流 | Redis 计数器实现，`pool/client` 生命周期注入 |
| `milvus.py` | Milvus 连接 | `connect/close/status/get_client`，未启用返回 None，调用方判空 |
| `rag_collections.py` | RAG 集合 | 启动时 `ensure_collections` 建集合与索引 |

#### 3.6 任务队列 `core/worker/settings.py`

**解析**：ARQ 的 `WorkerSettings`，定义队列名、连接参数与任务函数注册表；Docker Compose 里 `worker` 服务以 `arq app.logs.core.worker.settings.WorkerSettings` 启动。

#### 3.7 智能体层 `core/agents/`

| 模块 | 职责 |
| --- | --- |
| `qweather/` | 天气智能体三件套：`jwt.py`（和风 EdDSA JWT 签名）→ `client.py`（城市查询/实时天气/预报 + 文本格式化）→ `agent.py`（LangChain agent + 事件翻译出 `step/content/done` 协议，供 `/chat` 链路渲染） |
| `dingtalk/` | 钉钉智能体：`cli.py`（dws 白名单封装 + 结构化错误）→ `tools.py`（注册为 Agent 工具）→ `agent.py`（对话代理）→ `runtime.py` |
| `ecommerce/` | 电商导购（短期记忆已就绪）：`state.py`（AgentState，`add_messages` reducer）、`product/`（商品源：`base.py` 协议 + builtin/pgvector/milvus/hybrid 四实现，`build_product_source` 按配置切换） |
| `window.py` | 短期记忆窗口策略：`truncate/token` 已实现；`_estimate_tokens`（中 1 字 1 token、英 4 字符 1 token）、`_slice_by_tokens`（尾部向前预算裁剪）、`_remove_messages`（转 `RemoveMessage` 触发删除）等辅助齐备；summary/hybrid 待长期记忆配合 |
| `runtime.py` | `get_window_strategy()` 策略单例（懒加载，按 `ECOMMERCE_WINDOW_STRATEGY` 切换） |

### 第 4 层 · 中间件 `src/app/middleware/client_cache_middleware.py`

**解析**：`ClientCacheMiddleware(BaseHTTPMiddleware)` 对每个响应补 `Cache-Control: public, max-age=N`（默认 60s）。关键细节：**仅当响应头没有 `cache-control` 才补**——SSE 流式接口显式设了 `no-cache`，不会被覆盖，保证流式不被浏览器/代理缓存。

### 第 5 层 · MCP 服务 `src/mcp_servers/`

**`qweather_mcp/server.py`**：`FastMCP("qweather——mcp")` + `@mcp.tool` 注册 `query_qweather_now(city)`（城市→经纬度→实况→格式化文本）。工具元数据/参数校验/JSON-RPC 全由 FastMCP 处理。

**`task_mcp/server.py`**：个人任务管理，`psycopg` v3 直连 PostgreSQL。三个关键设计：
- 连接串用 `make_conninfo` 从配置拼装并自动转义特殊字符；连接池 `open=False` 惰性打开，首次调用工具才连库。
- **`ConnectionPoolProxy`**：psycopg 的 `ConnectionPool` 实现了 `__enter__/__exit__`，若直接作为 FastMCP `Depends` 返回值，会被依赖引擎当作上下文管理器进入/退出 → 首次解析后连接池被 `close()`，后续解析再 `open()` 抛 `PoolClosed`。代理不实现上下文协议、仅转发 `connection()`，规避该坑（ruff B008 的 5 处误报即来自 `Depends(get_pool)` 惯用法）。
- 提供任务增删改查工具、任务概览资源、每日复盘提示。

### 第 6 层 · 数据库迁移 `src/migrations/`

**解析**：Alembic 标准结构。`env.py` 从 `app.core.config import settings` 读取 `POSTGRES_URI`、从 `app.core.db.database import Base` 拿 metadata，`prepend_sys_path = src`（阶段 4 统一导入时联动）。迁移命令必须在项目根目录执行：`uv run alembic revision --autogenerate -m "..."` → `uv run alembic upgrade head`。

### 第 7 层 · 测试 `tests/`

| 文件 | 内容 |
| --- | --- |
| `conftest.py` | pytest fixtures：`client`（TestClient 包装 app）、`db` 等 |
| `test_health.py` | `/api/v1/health` 健康检查断言 |
| `test_agent_events.py` | 智能体事件流（step/content/done 协议）断言 |

**解析**：因为 `import app.main` 即构建整个应用（含挂载 MCP、合并 lifespan），测试天然覆盖「应用能否组装」这一层；`--skip-infra` 逻辑让无 Postgres/Redis 环境也能跑通健康检查类测试。

### 第 8 层 · 前端静态资源 `src/app/static/`

**解析**：原生 HTML/CSS/JS 单页（无构建链）。`index.html` 为出行简报主页（天气格局 + 随行向导），`dingtalk/` 下为钉协助手（助手页 + 操作台页）。通过 `/chat` 的 SSE 事件渲染「调用链路」区块；`_static_version` 自动版本号保证前端更新不被浏览器缓存。

### 第 9 层 · 多智能体编排（LangGraph supervisor）+ A2A 协议

**编排器 `src/app/logs/core/agents/orchestrator/`**：单入口把 qweather / dingtalk / ecommerce 三个子智能体调度起来。

- `protocol.py`：`BaseSubAgent` 统一调用契约（`name` / `description` / `stream`，`run` 为 `stream` 的非流式默认实现）；`context` 预留透传 `user_id` / `conversation_id`。
- 三个适配器：`qweather_adapter.py` / `dingtalk_adapter.py` / `ecommerce_adapter.py`，把各子智能体的流式回答「适配」成协议（电商适配器从 `context` 取用户会话维度）。
- `engine.py`：LangGraph supervisor 循环 —— `supervisor` 节点（大模型 + 工具壳）+ `tools` 节点（查注册表执行子智能体）+ 条件边；`invoke` 非流式入口，`stream_answer` 用 `astream_events` 缓冲过渡输出、只吐最终回答。
- 包导入即默认 `register_agent` 三个子智能体；新增子智能体只需写适配类 + 注册一行。
- 接口：`POST /api/v1/orchestrator/chat`（SSE），`context` 一路透传到电商子智能体。

**A2A 协议 `src/app/logs/core/agents/a2a/`**：基于 **官方 `a2a-sdk`（1.2.2）** 把每个子智能体暴露为独立 A2A 服务（名片发现 + JSON-RPC 任务委托）。

- `executor.py`：`SubAgentExecutor` —— 用 `AgentExecutor` 包装 `BaseSubAgent`。任务事件顺序严格符合 SDK：先 enqueue 初始 `Task(SUBMITTED)`，需确认则改为 `INPUT_REQUIRED` 并携带 `original_request`，否则 `start_work()` → 逐段 `add_artifact(append=...)` → `complete()`；异常 catch 后 `_mark_failed` 置为 failed 而不抛出。
- `server.py`：`build_agent_card`（Agent Card，挂在 `/.well-known/agent-card.json`）、`build_task_store`（`memory | sqlite | postgres` 三档，Postgres 用共享引擎）、`build_agent_a2a_app`（`DefaultRequestHandler` + `add_a2a_routes_to_fastapi`）、`build_a2a_mounts`（返回 `{name: app}` 供挂载到 `/a2a/{name}`）、`a2a_lifespan`（启动建表、退出释放引擎）。
- `client.py`：`A2ASubAgent`（实现 `BaseSubAgent`）——复用 httpx 连接池、瞬态网络错误指数退避重试、`stream()` 兼容 `task / artifact_update / message` payload、`confirm()` 实现确认闭环、`awaiting_confirmation`。`_build_request` 在 metadata 里透传 `confirmed` 以规避远端服务端双重门禁。
- 编排器通过 `ORCHESTRATOR_SUBAGENT_TRANSPORT` 切换 `inprocess`（进程内）或 `a2a`（远程经 `/a2a/{name}`）。

**确认门禁（Confirmation Gate）**：`/orchestrator` 三大子智能体中钉钉设置为 `confirmation_required = True`。流程：`engine.tools_node` 发现需要确认 → 抛 `ConfirmationRequired` → `api/v1/orchestrator.py` 捕获并 `store_pending` → SSE 下发 `{"confirm_required": {...}}` → 前端显示确认/取消按钮 → `POST /orchestrator/confirm` 用 `confirmed: True` 重放 `stream_answer`。A2A 侧同样有 `original_request` + `confirmed` 元数据闭环。

### 层间数据流速览

```
浏览器(/ 或 /dingtalk) ←static 页面→ setup.py
浏览器 /api/v1/* ←→ api 路由 ←→ core(agents / deepseek / security / db / utils)
                                  └→ Postgres / Redis / Milvus / 和风 API / DWS CLI / DeepSeek
MCP 客户端 /qweather_mcp、/task-mcp ←→ FastMCP 应用 ←→ core.agents.qweather.client / Postgres(psycopg)
```

---

## 阶段 8 · 2026-10-10：对外公告发布审批智能体（Human-in-the-loop）

**规划**：参照「LangGraph Human-in-the-loop」教程与公告审批实战文档，落地一个在关键操作前暂停、等待人工审批的公告发布闭环，补齐此前只做了「配置 + 数据模型 + 图状态」的半成品。

**怎么做**：LangGraph `interrupt` 暂停 + `Command(resume=...)` 恢复；风险分流（low 自动发布 / high 进入人工审批）；四种人工响应 approve / edit / reject / cancel；业务记录 `announcements` + 审计日志 `approval_records` 两张表；暂停状态用检查点持久化。

**做了什么**：

- 新增 `src/app/logs/core/agents/announcement/` 包：`dingtalk_channel.py`（群名解析、群公告发布、机器人审批通知，复用钉钉 `cli.py` 白名单动作 `group_search` / `notice_create` / `robot_send`）、`graph.py`（核心 HITL 图）、`service.py`（提交/查询/回填服务层）、`__init__.py`。
- 新增 `src/app/api/v1/announcement.py` 路由（`/api/v1/announcements`，提交/列表/详情/回填），并在 `api/v1/__init__.py` 注册。
- 依赖新增 `langgraph-checkpoint-postgres`（3.x）。
- 检查点**复用** `ecommerce.checkpointer.get_checkpointer()`（与客服智能体一致），未单独造同步包装——文档中的同步 PostgresSaver 包装基于旧版 API（`PostgresSaver(pool)`），与新装的 3.1.2 不兼容，故采用项目既有检查点设施；顺带按 `ecommerce/checkpointer.py` 内注释补回 `type: ignore[arg-type]`（依赖补齐后 AsyncPostgresSaver 有了真实类型）。
- 新增 `tests/test_announcement.py` 10 条冒烟测试（check 分流、interrupt 暂停、四种响应恢复、路由注册），全部用 MemorySaver，不依赖 Postgres / 钉钉 / 大模型。

**成果总结**：`ruff check`、`mypy src tests`、`pytest`（76 条）全绿。低风险公告自动发布，高风险公告在 human_review 暂停等待人工回填，四种响应经 `Command(resume=...)` 恢复执行并落审计。

---

## 附：当前项目组成快照

| 组成 | 说明 |
| --- | --- |
| 后端入口 | `src/app/main.py` → `app.main:app`，路由前缀 `/api/v1/` |
| 路由 | auth / dingtalk / ecommerce / milvus / orchestrator / products / qweather / customer_service / analyst / announcement（含 `/health` 探针） |
| 智能体 | 天气（qweather）+ 钉钉（dingtalk）+ 电商导购（ecommerce，短期记忆已就绪）+ 编排器（orchestrator，LangGraph supervisor）+ 客服（customer_service）+ 分析（analyst）+ 公告审批（announcement，Human-in-the-loop）+ A2A 协议（名片 / 任务委托 / 远程适配器） |
| MCP 服务 | `mcp_servers/qweather_mcp`、`task_mcp`（FastMCP，挂载于 FastAPI） |
| 记忆体系 | 短期记忆（Checkpointer + 窗口策略）已实现；长期记忆（UserProfile/UserMemory 模型已建，逻辑待做） |
| 部署 | Dockerfile + docker-compose（web/worker/db/redis）+ DEPLOY.md 逐步手册 |

## 附：常用命令速查

```sh
uv sync                                          # 安装/同步依赖
uv run python src/run.py --skip-infra            # 本地快速启动（8888 端口）
uv run python -m pytest                          # 运行测试
uv run ruff check --fix && uv run ruff format    # 修复并格式化代码
uv run alembic revision --autogenerate -m "..."  # 生成迁移（项目根目录）
uv run alembic upgrade head                      # 应用迁移
```
