"""编排器 API：单入口对话，自动路由到子智能体。

通过 SSE 暴露 :func:`app.logs.core.agents.orchestrator.stream_answer`，
一个入口把天气 / 钉钉 / 电商三个子智能体调度起来，并透传
``user_id`` / ``conversation_id`` 给有状态的子智能体。

需要确认的子智能体（钉钉写操作等）会先返回 ``confirm_required`` 事件，
前端据此展示确认 UI，确认后经 POST ``/confirm`` 恢复执行。
"""

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.logs.core.agents.orchestrator import ConfirmationRequired, stream_answer
from app.logs.core.agents.orchestrator.confirmation import pop_pending, store_pending

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestrator", tags=["多智能体编排"])


class ChatRequest(BaseModel):
    """编排器问答请求体。"""

    question: str = Field(..., min_length=1, description="用户本轮消息")
    user_id: int = Field(0, description="用户 id（电商导购等有状态子智能体使用）")
    conversation_id: str | None = Field(None, description="会话 id；为空则新建会话")


class ConfirmRequest(BaseModel):
    """确认请求体：回传用户对某条待确认请求的决定。"""

    confirm_id: str = Field(..., description="待确认请求 id（来自 confirm_required 事件）")
    approved: bool = Field(True, description="True 确认执行，False 取消")
    user_id: int = Field(0, description="与发起请求时一致的用户 id")
    conversation_id: str | None = Field(None, description="与发起请求时一致的会话 id")


@router.post("/chat", summary="单入口对话：自动路由到子智能体")
async def chat(req: ChatRequest) -> StreamingResponse:
    """编排入口（流式 SSE）：透传子智能体，或汇总多个子智能体，或闲聊回答。

    客户端会收到 ``data: {"text": "..."}`` 的逐段文本，最后 ``data: {"done": true}``
    表示本轮结束；需要确认时下发 ``data: {"confirm_required": {...}}``；
    出错时下发 ``data: {"error": "..."}``。
    """

    async def event_stream() -> AsyncGenerator[str]:
        context = {"user_id": req.user_id, "conversation_id": req.conversation_id}
        try:
            async for text in stream_answer(req.question, context=context):
                yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
        except ConfirmationRequired as cr:
            # 子智能体需要确认：存下待确认请求，把确认提示 + confirm_id 发给前端
            confirm_id = store_pending(cr.agent_name, cr.message, cr.context)
            payload = {
                "message": cr.prompt,
                "agent_name": cr.agent_name,
                "confirm_id": confirm_id,
            }
            yield f"data: {json.dumps({'confirm_required': payload}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("编排器回答失败")
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/confirm", summary="确认/取消待确认的子智能体操作")
async def confirm(req: ConfirmRequest) -> dict[str, object]:
    """对某条待确认请求回传决定（确认执行 / 取消），恢复被搁置的流程。"""
    pending = pop_pending(req.confirm_id)
    if pending is None:
        return {"ok": False, "message": "确认请求不存在或已处理", "executed": None}
    if not req.approved:
        return {"ok": True, "message": "已取消该操作", "executed": False}

    # 确认执行：携带 confirmed 标记重放子智能体，此时跳过确认门禁
    context = dict(pending.context or {})
    context.update({"user_id": req.user_id, "conversation_id": req.conversation_id, "confirmed": True})
    chunks = [text async for text in stream_answer(pending.message, context=context)]
    return {"ok": True, "message": "".join(chunks), "executed": True}
