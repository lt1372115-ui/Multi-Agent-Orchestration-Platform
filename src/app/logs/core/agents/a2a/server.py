"""A2A 服务端：用官方 a2a-sdk 把子智能体暴露为独立 A2A 服务。

对应「第四章 A2A 协议」文档第 2、5 步：
- 每个子智能体一张 Agent Card（``/.well-known/agent-card.json``）做能力发现；
- 每个子智能体一个独立 FastAPI 子应用（Agent Card + JSON-RPC），挂到 ``/a2a/{name}``；
- 任务存储按 ``memory | sqlite | postgres`` 三档可切换，Postgres 跨子智能体共享连接池；
- 基础设施生命周期：启动时初始化建表、退出时释放连接池。
"""

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.logs.core.agents.a2a.executor import SubAgentExecutor
from app.logs.core.agents.orchestrator.protocol import BaseSubAgent
from app.logs.core.config import settings

logger = logging.getLogger(__name__)


def build_agent_card(agent: BaseSubAgent, *, base_url: str, interface_url: str) -> Any:
    """为一个子智能体构建 A2A Agent Card（官方 a2a-sdk 的 ``types.AgentCard``）。"""
    from a2a import types
    from a2a.utils.constants import TransportProtocol

    return types.AgentCard(
        name=agent.name,
        description=agent.description,
        version="1.0.0",
        capabilities=types.AgentCapabilities(streaming=True),
        skills=[types.AgentSkill(id=agent.name, name=agent.name, description=agent.description)],
        default_input_modes=["text"],
        default_output_modes=["text"],
        provider=types.AgentProvider(url=base_url),
        supported_interfaces=[
            types.AgentInterface(
                url=interface_url,
                protocol_binding=TransportProtocol.JSONRPC,
                protocol_version="1.0",
            )
        ],
    )


def _build_sqlite_store(agent_name: str) -> Any:
    """构建 SQLite 持久化任务存储（单文件，适合本地/单实例）。"""
    from a2a.server.tasks.database_task_store import DatabaseTaskStore
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///./storage/a2a_tasks_{agent_name}.db")
    return DatabaseTaskStore(engine=engine, table_name=f"a2a_tasks_{agent_name}")


def _build_postgres_engine() -> Any:
    """懒加载并复用 PostgreSQL 异步引擎（连接池跨子智能体共享）。"""
    global _postgres_engine
    if not settings.A2A_POSTGRES_URL:
        raise RuntimeError("A2A_TASK_STORE=postgres 需要设置 A2A_POSTGRES_URL")
    if _postgres_engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine

        # A2A_POSTGRES_URL 是主机串（user:pwd@host:port/db），补上 asyncpg 方言前缀
        url = f"postgresql+asyncpg://{settings.A2A_POSTGRES_URL}"
        _postgres_engine = create_async_engine(url, pool_pre_ping=True)
    return _postgres_engine


def _build_postgres_store(agent_name: str) -> Any:
    """构建 PostgreSQL 持久化任务存储（多实例可共享任务状态）。"""
    from a2a.server.tasks.database_task_store import DatabaseTaskStore

    return DatabaseTaskStore(engine=_build_postgres_engine(), table_name=f"a2a_tasks_{agent_name}")


def build_task_store(agent_name: str) -> Any:
    """按配置构建任务存储：memory（进程内）| sqlite | postgres。"""
    from a2a.server.tasks import InMemoryTaskStore

    if settings.A2A_TASK_STORE == "sqlite":
        store = _build_sqlite_store(agent_name)
    elif settings.A2A_TASK_STORE == "postgres":
        store = _build_postgres_store(agent_name)
    else:
        store = InMemoryTaskStore()
    _task_stores.append(store)
    return store


def build_agent_a2a_app(agent: BaseSubAgent, *, base_url: str, interface_url: str) -> FastAPI:
    """为一个子智能体构建独立的 A2A 应用（Agent Card 发现 + JSON-RPC）。"""
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes

    card = build_agent_card(agent, base_url=base_url, interface_url=interface_url)
    handler = DefaultRequestHandler(
        agent_executor=SubAgentExecutor(agent),
        task_store=build_task_store(agent.name),
        agent_card=card,
    )
    app = FastAPI(title=f"A2A Agent: {agent.name}")
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
    )
    return app


def build_a2a_mounts(agents: Sequence[BaseSubAgent], *, base_url: str) -> dict[str, FastAPI]:
    """为多个子智能体构建独立 A2A 应用，返回 ``{name: app}`` 供挂载。"""
    return {
        agent.name: build_agent_a2a_app(
            agent,
            base_url=base_url,
            interface_url=f"{base_url.rstrip('/')}/a2a/{agent.name}",
        )
        for agent in agents
    }


async def _dispose_postgres_engine() -> None:
    """释放 PostgreSQL 共享引擎（幂等）。"""
    global _postgres_engine
    if _postgres_engine is not None:
        await _postgres_engine.dispose()
        _postgres_engine = None


@asynccontextmanager
async def a2a_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """A2A 基础设施生命周期：启动时初始化任务存储（建表），退出时释放共享引擎。"""
    for store in _task_stores:
        initialize = getattr(store, "initialize", None)
        if initialize is not None:
            await initialize()
    yield
    await _dispose_postgres_engine()


# 已构建的任务存储（供应用生命周期初始化建表）
_task_stores: list = []
# PostgreSQL 共享引擎（多个子智能体共用同一个连接池）
_postgres_engine: Any = None
