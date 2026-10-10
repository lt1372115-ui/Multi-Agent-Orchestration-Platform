"""分析智能体的进程内适配实现。"""

from collections.abc import AsyncIterator
from typing import Any

from app.logs.core.agents.analyst import agent as analyst_agent
from app.logs.core.agents.ecommerce.session import new_conversation_id
from app.logs.core.agents.orchestrator.protocol import BaseSubAgent


class AnalystSubAgent(BaseSubAgent):
    """把分析智能体包装成编排器可调用的子智能体（按会话隔离短期记忆）。"""

    name = "analyst"
    description = "运营分析助手：生成运营日报，分析订单量、销售额、用户增长、转化率等核心经营指标。"

    async def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        """透传分析智能体的流式回答，并按 conversation_id 隔离短期记忆。"""
        ctx = context or {}
        conversation_id = ctx.get("conversation_id") or new_conversation_id()
        async for chunk in analyst_agent.stream_answer(message, conversation_id):
            yield chunk
