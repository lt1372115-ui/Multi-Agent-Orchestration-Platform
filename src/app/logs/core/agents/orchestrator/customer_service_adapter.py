"""客服智能体的进程内适配实现。"""

from collections.abc import AsyncIterator
from typing import Any

from app.logs.core.agents.customer_service import agent as customer_service_agent
from app.logs.core.agents.ecommerce.session import new_conversation_id
from app.logs.core.agents.orchestrator.protocol import BaseSubAgent


class CustomerServiceSubAgent(BaseSubAgent):
    """把客服智能体包装成编排器可调用的子智能体（按会话隔离短期记忆）。"""

    name = "customer_service"
    description = "客服助手：订单查询（状态、物流、退款进度）、常见问题解答与售后咨询。"

    async def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        """透传客服智能体的流式回答，并按 conversation_id 隔离短期记忆。"""
        ctx = context or {}
        conversation_id = ctx.get("conversation_id") or new_conversation_id()
        async for chunk in customer_service_agent.stream_answer(message, conversation_id):
            yield chunk
