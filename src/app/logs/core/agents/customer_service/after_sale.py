"""客服退换货申请抽象层：内置演示退换货申请，后续可替换为真实售后系统。

业务代码只依赖 :class:`ReturnSource` 协议，切换退换货来源只需修改
``CUSTOMER_SERVICE_RETURN_SOURCE`` 配置：当前仅 ``builtin``（内置演示数据），
真实售后系统（http / postgres）可在此按协议新增后端。
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import uuid4

from app.logs.core.config import settings

logger = logging.getLogger(__name__)

# 退换货类型白名单，非法取值回退为「退货」
_VALID_ACTIONS = ("退货", "换货")


@dataclass
class ReturnRequest:
    """一条退换货申请。"""

    request_id: str
    order_id: str
    action: str
    reason: str
    status: str
    created_at: str

    def to_text(self) -> str:
        """转为适合大模型阅读的简洁文本。"""
        return (
            f"退换货申请已提交\n"
            f"申请单号：{self.request_id}\n"
            f"订单号：{self.order_id}\n"
            f"类型：{self.action}\n"
            f"原因：{self.reason}\n"
            f"状态：{self.status}\n"
            f"申请时间：{self.created_at}\n"
            "预计 1-3 个工作日内审核，审核通过后将有客服联系您。"
        )


@runtime_checkable
class ReturnSource(Protocol):
    """退换货申请的统一接口。新来源只需实现本协议并在 :func:`build_return_source` 注册。"""

    async def apply(self, order_id: str, action: str, reason: str) -> ReturnRequest | None:
        """提交退换货申请，订单不存在时返回 None。"""
        ...


class BuiltinReturnSource(ReturnSource):
    """基于内置演示数据的退换货申请，提交前会先校验订单是否存在。"""

    async def apply(self, order_id: str, action: str, reason: str) -> ReturnRequest | None:
        from app.logs.core.agents.customer_service.order import build_order_source

        order = await build_order_source().lookup(order_id)
        if order is None:
            return None
        normalized_action = action if action in _VALID_ACTIONS else "退货"
        return ReturnRequest(
            request_id=f"RT{uuid4().hex[:10].upper()}",
            order_id=order.order_id,
            action=normalized_action,
            reason=reason.strip() or "未说明原因",
            status="待审核",
            created_at=datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        )


def build_return_source(source: str | None = None) -> ReturnSource:
    """根据配置创建退换货申请源。当前仅支持内置演示数据。"""
    source = source or settings.CUSTOMER_SERVICE_RETURN_SOURCE
    if source != "builtin":
        raise NotImplementedError(
            f"CUSTOMER_SERVICE_RETURN_SOURCE={source} 尚未实现，请改用 builtin 或接入真实售后系统"
        )
    logger.info("退换货申请源：builtin（内置演示数据）")
    return BuiltinReturnSource()
