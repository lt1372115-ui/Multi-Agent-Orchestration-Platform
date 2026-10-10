"""钉钉 DWS 直连接口：把通讯录、日程、待办、消息等操作暴露为 HTTP 接口。

所有操作经由 :mod:`app.logs.core.agents.dingtalk.cli` 的白名单封装执行，
写操作额外受 ``DINGTALK_ENABLE_WRITE`` 开关与请求体 ``confirm`` 字段控制。
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.logs.core.agents.dingtalk import agent as dingtalk_agent, cli as dingtalk_cli
from app.logs.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dingtalk", tags=["dingtalk"])


def _as_http(exc: dingtalk_cli.DingTalkError) -> HTTPException:
    """把钉钉 CLI 的失败映射成带原因的状态码。"""
    if isinstance(exc, dingtalk_cli.DingTalkNotInstalledError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, dingtalk_cli.DingTalkWriteDisabledError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _run(action: str, **params: Any) -> str:
    """执行钉钉 CLI 动作，并保证失败原因能传到前端。

    直接让 RuntimeError 冒泡的话，客户端只会收到 ``Internal Server Error``，
    看不到缺的究竟是哪一步。
    """
    try:
        return dingtalk_cli.run_dws(action, **params)
    except dingtalk_cli.DingTalkError as exc:
        raise _as_http(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health")
def dingtalk_health() -> dict[str, Any]:
    """检查 dws CLI 是否可用。"""
    return {"dws_available": dingtalk_cli.is_available()}


@router.get("/auth/status")
def auth_status() -> dict[str, Any]:
    """查询钉钉登录状态。"""
    try:
        return dingtalk_cli.auth_status()
    except dingtalk_cli.DingTalkError as exc:
        raise _as_http(exc) from exc


@router.post("/auth/login")
def auth_login() -> dict[str, Any]:
    """触发钉钉扫码登录（会在本机打开浏览器授权）。"""
    try:
        dingtalk_cli.auth_login()
    except dingtalk_cli.DingTalkError as exc:
        raise _as_http(exc) from exc
    return {"triggered": True, "message": "已触发登录，请在浏览器完成授权"}


# ---------------- 直连：读操作 ----------------


@router.get("/contact/search")
def contact_search(query: str) -> dict[str, Any]:
    """搜索钉钉通讯录联系人。"""
    return {"result": _run("contact_search", query=query)}


@router.get("/calendar/list")
def calendar_list() -> dict[str, Any]:
    """查询今天的钉钉日程。"""
    return {"result": _run("calendar_list")}


@router.get("/todo/list")
def todo_list(include_done: bool = False, priority: str | None = None) -> dict[str, Any]:
    """查询我的钉钉待办。"""
    status = "true" if include_done else "false"
    return {"result": _run("todo_list", status=status, priority=priority)}


@router.get("/log/list")
def log_list() -> dict[str, Any]:
    """查询我收到的钉钉日志。"""
    return {"result": _run("log_list")}


@router.get("/attendance")
def attendance() -> dict[str, Any]:
    """查询我今天的钉钉考勤打卡流水。"""
    return {"result": _run("attendance_get")}


@router.get("/group/search")
def group_search(query: str) -> dict[str, Any]:
    """按关键词搜索钉钉群聊。"""
    return {"result": _run("group_search", query=query)}


# ---------------- 直连：写操作 ----------------


class CalendarCreateRequest(BaseModel):
    """创建日程请求体。"""

    title: str
    start: str
    end: str
    attendees: str | None = None
    confirm: bool = False


class TodoCreateRequest(BaseModel):
    """给自己创建待办请求体。"""

    task: str
    at: str | None = None
    confirm: bool = False


class TodoAssignRequest(BaseModel):
    """给同事指派待办请求体。"""

    task: str
    to: str
    due: str | None = None
    confirm: bool = False


class MessageSendRequest(BaseModel):
    """发送单聊消息请求体。

    ``to``（姓名）与 ``open_dingtalk_id`` 二选一：同名多人时只能用后者。
    """

    content: str
    to: str | None = None
    open_dingtalk_id: str | None = None
    confirm: bool = False


class GroupMessageSendRequest(BaseModel):
    """发送群消息请求体。"""

    group: str
    content: str
    confirm: bool = False


class DingSendRequest(BaseModel):
    """发送 DING 请求体。"""

    users: str
    content: str
    method: str = "app"
    confirm: bool = False


class SheetCreateRequest(BaseModel):
    """创建在线表格请求体。"""

    name: str
    folder: str | None = None
    workspace: str | None = None
    confirm: bool = False


class LogCreateRequest(BaseModel):
    """提交日志请求体。"""

    template_id: str
    contents: str
    to_user_ids: str
    confirm: bool = False


class NoticeCreateRequest(BaseModel):
    """发布群公告请求体。"""

    conversation_id: str
    content: str
    sticky: bool = False
    send_ding: bool = False
    confirm: bool = False


class RobotMessageSendRequest(BaseModel):
    """发送机器人消息请求体。"""

    content: str
    confirm: bool = False


@router.post("/calendar")
def calendar_create(req: CalendarCreateRequest) -> dict[str, Any]:
    """创建钉钉日程。"""
    return {
        "result": _run(
            "calendar_create",
            title=req.title,
            start=req.start,
            end=req.end,
            attendees=req.attendees,
            confirm=req.confirm,
        )
    }


@router.post("/todo")
def todo_create(req: TodoCreateRequest) -> dict[str, Any]:
    """给自己创建钉钉待办。"""
    return {"result": _run("todo_remind", task=req.task, at=req.at, confirm=req.confirm)}


@router.post("/todo/assign")
def todo_assign(req: TodoAssignRequest) -> dict[str, Any]:
    """给同事指派钉钉待办。"""
    return {"result": _run("todo_assign", task=req.task, to=req.to, due=req.due, confirm=req.confirm)}


@router.post("/message/send")
def message_send(req: MessageSendRequest) -> dict[str, Any]:
    """发送钉钉单聊消息。收件人同名多人时改用 open_dingtalk_id 指定唯一用户。"""
    if bool(req.to) == bool(req.open_dingtalk_id):
        raise HTTPException(status_code=400, detail="to（收件人姓名）与 open_dingtalk_id 必须二选一")
    return {
        "result": _run(
            "message_send",
            identity="user",
            to_query=req.to,
            open_dingtalk_id=req.open_dingtalk_id,
            content=req.content,
            confirm=req.confirm,
        )
    }


@router.post("/group-message/send")
def group_message_send(req: GroupMessageSendRequest) -> dict[str, Any]:
    """发送钉钉群消息。"""
    return {"result": _run("group_message_send", group=req.group, content=req.content, confirm=req.confirm)}


@router.post("/ding/send")
def ding_send(req: DingSendRequest) -> dict[str, Any]:
    """发送钉钉 DING 强提醒。"""
    return {"result": _run("ding_send", users=req.users, content=req.content, method=req.method, confirm=req.confirm)}


@router.post("/sheet")
def sheet_create(req: SheetCreateRequest) -> dict[str, Any]:
    """创建钉钉在线表格。"""
    return {
        "result": _run("sheet_create", name=req.name, folder=req.folder, workspace=req.workspace, confirm=req.confirm)
    }


@router.post("/log")
def log_create(req: LogCreateRequest) -> dict[str, Any]:
    """提交钉钉日志。"""
    return {
        "result": _run(
            "log_create",
            template_id=req.template_id,
            contents=req.contents,
            to_user_ids=req.to_user_ids,
            confirm=req.confirm,
        )
    }


@router.post("/notice")
def notice_create(req: NoticeCreateRequest) -> dict[str, Any]:
    """发布钉钉群公告。"""
    return {
        "result": _run(
            "notice_create",
            conversation_id=req.conversation_id,
            content=req.content,
            sticky=req.sticky,
            send_ding=req.send_ding,
            confirm=req.confirm,
        )
    }


@router.post("/robot-message/send")
def robot_message_send(req: RobotMessageSendRequest) -> dict[str, Any]:
    """通过群自定义机器人（Webhook）发送消息。"""
    token = settings.DINGTALK_ROBOT_WEBHOOK_TOKEN
    if not token:
        raise HTTPException(
            status_code=503,
            detail="未配置 DINGTALK_ROBOT_WEBHOOK_TOKEN，请在 src/.env 中配置群机器人 Webhook token",
        )
    return {
        "result": _run(
            "robot_send",
            identity="webhook",
            webhook_token=token,
            text=req.content,
            confirm=req.confirm,
        )
    }


# ---------------- 智能体：流式对话 ----------------


class ChatRequest(BaseModel):
    """钉协助手智能体问答请求体。"""

    question: str


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """钉协助手智能体问答（流式 SSE）：模型自行调用钉钉工具后给出结果。

    每条事件都以 ``data: `` 开头，内容为 JSON：

    - ``{"type": "tool", "name": str, "args": dict}``：模型决定调用某个钉钉工具。
    - ``{"type": "content", "content": "..."}``：回答文本片段。
    - ``{"type": "error", "message": "..."}``：生成过程失败。
    - ``{"type": "done"}``：本次回答结束，流中保证只出现一次。
    """

    async def event_stream() -> AsyncGenerator[str]:
        finished = False
        try:
            async for event in dingtalk_agent.stream_events(req.question):
                finished = finished or event["type"] == "done"
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("钉协助手回答失败")
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
