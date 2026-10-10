"""分析智能体路由：SSE 流式问答（生成运营日报等）。"""

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.logs.core.agents.analyst import agent as analyst_agent
from app.logs.core.agents.ecommerce.session import new_conversation_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyst", tags=["分析智能体"])


class ChatRequest(BaseModel):
    """智能体问答请求体。"""

    question: str
    conversation_id: str | None = None


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """智能体问答（SSE 流式）：模型生成回答，并回传调用链路。

    每条事件都以 ``data: `` 开头，内容为 JSON：

    - ``{"type": "conversation", "conversation_id": "..."}`` 本次会话 id，客户端保存后
      回传可延续同一会话的短期记忆。
    - ``{"type": "step", "phase": "start", ...}`` 链路节点开始。``kind`` 为 ``model``
      （模型某一轮思考）或 ``tool``（工具调用）；``id`` 用于把同一节点的 start / end 配对。
    - ``{"type": "step", "phase": "end", ...}`` 链路节点结束，带 ``status`` 与 ``elapsed_ms``。
    - ``{"type": "content", "content": "..."}`` 回答文本片段。
    - ``{"type": "error", "message": "..."}`` 生成过程失败。
    - ``{"type": "done", "elapsed_ms": int, "path": [...]}`` 本次回答结束。
    """

    conversation_id = req.conversation_id or new_conversation_id()

    async def event_stream() -> AsyncGenerator[str]:
        finished = False
        try:
            conversation = {"type": "conversation", "conversation_id": conversation_id}
            yield f"data: {json.dumps(conversation, ensure_ascii=False)}\n\n"
            async for event in analyst_agent.stream_events(req.question, conversation_id):
                finished = finished or event["type"] == "done"
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("智能体回答失败")
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        if not finished:
            # 异常或中断时补一个终止标记，保证前端总能收到 done
            yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
