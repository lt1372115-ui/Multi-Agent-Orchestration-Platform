"""编排器的确认机制：待确认请求的存储与 ``ConfirmationRequired`` 信号。

嵌套在编排器一层，统一 inprocess 与 a2a 两种传输的确认行为——
子智能体一旦声明 ``confirmation_required``，无论本地还是远程，都先过同一扇门。
"""

from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import uuid4

# 待确认请求的保留时长与容量上限：用户始终不确认（或前端丢失 confirm_id）时，
# 进程内表不能无界增长；过期条目在下一次写入/查询时顺带清理。
_PENDING_TTL_SECONDS = 1800
_PENDING_MAX_ITEMS = 512


class ConfirmationRequired(Exception):  # noqa: N818
    """子智能体需要用户确认后才能执行的信号。"""

    def __init__(self, agent_name: str, message: str, context: dict[str, Any] | None, prompt: str) -> None:
        super().__init__(prompt)
        self.agent_name = agent_name
        self.message = message
        self.context = context
        self.prompt = prompt


@dataclass
class PendingConfirmation:
    """一条等待用户确认的请求。"""

    confirm_id: str
    agent_name: str
    message: str
    context: dict[str, Any] | None
    created_at: float = 0.0


# 进程内的待确认请求表；生产多实例部署时需换成 Redis / 数据库等共享存储。
_pending: dict[str, PendingConfirmation] = {}


def _purge(now: float) -> None:
    """清理过期条目，并在超容量时丢弃最早的一条。"""
    for confirm_id in [cid for cid, item in _pending.items() if now - item.created_at > _PENDING_TTL_SECONDS]:
        _pending.pop(confirm_id, None)
    while len(_pending) >= _PENDING_MAX_ITEMS:
        oldest = min(_pending.items(), key=lambda item: item[1].created_at)[0]
        _pending.pop(oldest, None)


def store_pending(agent_name: str, message: str, context: dict[str, Any] | None) -> str:
    """存入一条待确认请求，返回其 ``confirm_id``。"""
    now = monotonic()
    _purge(now)
    confirm_id = uuid4().hex
    _pending[confirm_id] = PendingConfirmation(
        confirm_id=confirm_id,
        agent_name=agent_name,
        message=message,
        context=context,
        created_at=now,
    )
    return confirm_id


def pop_pending(confirm_id: str) -> PendingConfirmation | None:
    """取出并删除一条待确认请求；不存在返回 ``None``。"""
    return _pending.pop(confirm_id, None)


def has_pending(context: dict[str, Any] | None) -> bool:
    """同一会话（``user_id:conversation_id``）是否已有未决的确认请求。

    有未决确认时，新一轮的工具调用不再重复弹确认框，避免用户被旧操作反复打断。
    """
    if not context:
        return False
    _purge(monotonic())
    user_id = int(context.get("user_id", 0) or 0)
    conversation_id = context.get("conversation_id")
    if not conversation_id:
        return False
    return any(
        p.context is not None
        and int(p.context.get("user_id", 0) or 0) == user_id
        and p.context.get("conversation_id") == conversation_id
        for p in _pending.values()
    )
