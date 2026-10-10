"""A2A（Agent2Agent）协议层：官方 a2a-sdk 的流式任务、确认流程与远程客户端。

对应「第四章 A2A 协议」文档：用官方 a2a-sdk 把子智能体暴露为独立 A2A 服务
（每个子智能体一张 Agent Card + JSON-RPC 端点），并用 ``A2ASubAgent`` 客户端把
远程 Agent 包装成与进程内适配器一致的 ``BaseSubAgent`` 契约，编排器无需改动。
"""

from app.logs.core.agents.a2a.client import A2ASubAgent
from app.logs.core.agents.a2a.executor import SubAgentExecutor
from app.logs.core.agents.a2a.server import (
    a2a_lifespan,
    build_a2a_mounts,
    build_agent_a2a_app,
    build_agent_card,
    build_task_store,
)

__all__ = [
    "A2ASubAgent",
    "SubAgentExecutor",
    "a2a_lifespan",
    "build_a2a_mounts",
    "build_agent_a2a_app",
    "build_agent_card",
    "build_task_store",
]
