"""钉协助手子智能体的进程内适配实现。"""

from collections.abc import AsyncIterator
from typing import Any

from app.logs.core.agents.dingtalk import agent as dingtalk_agent
from app.logs.core.agents.orchestrator.protocol import BaseSubAgent


class DingTalkSubAgent(BaseSubAgent):
    """把钉协助手智能体包装成编排器可调用的子智能体。"""

    name = "dingtalk"
    description = "钉钉办公助手：通讯录搜索、日历日程、待办、消息与 DING、日志、考勤等办公操作。"
    confirmation_required = True  # 钉钉写操作（发消息/日程/待办等）需先确认

    async def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        """直接透传钉协助手智能体的流式回答。"""
        async for chunk in dingtalk_agent.stream_answer(message):
            yield chunk
