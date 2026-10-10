"""电商导购智能体路由：带长期记忆的流式对话。

对外通过 SSE 暴露 :func:`app.logs.core.agents.ecommerce.stream.stream_chat`，
把电商客服的长期记忆（记忆召回 + 画像注入 + 窗口压缩）接成可用的 HTTP 接口。
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.logs.core.agents.ecommerce.session import new_conversation_id
from app.logs.core.agents.ecommerce.stream import stream_chat
from app.logs.core.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ecommerce", tags=["电商导购智能体"])


class ChatRequest(BaseModel):
    """电商导购智能体问答请求体。"""

    message: str
    conversation_id: str | None = None


@router.post("/chat/stream", summary="带长期记忆的电商导购流式对话")
async def chat_stream(
    request: ChatRequest,
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> StreamingResponse:
    """流式对话（SSE）：分 token 返回回答文本。

    每条事件都以 ``data: `` 开头，内容为 JSON：

    - ``{"type": "conversation", "conversation_id": "..."}``：本次会话 id，
      客户端可保存后回传以延续同一会话的短期记忆。
    - ``{"type": "text", "text": "..."}``：回答文本片段。
    - ``{"type": "error", "message": "..."}``：生成过程失败。
    - ``{"type": "done"}``：本次流结束，保证只出现一次。

    ``conversation_id`` 为空时自动新建会话。鉴权使用 Bearer 令牌（JWT），
    解析出的 ``user_id`` 作为长期记忆与短期记忆的隔离维度。
    """
    conversation_id = request.conversation_id or new_conversation_id()

    async def event_stream() -> AsyncGenerator[str]:
        try:
            conversation = {"type": "conversation", "conversation_id": conversation_id}
            yield f"data: {json.dumps(conversation, ensure_ascii=False)}\n\n"
            async for text in stream_chat(user_id, request.message, conversation_id):
                payload = {"type": "text", "text": text}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("电商导购智能体回答失败")
            error = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
