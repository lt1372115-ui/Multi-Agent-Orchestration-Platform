"""客服订单查询抽象层：内置演示订单数据，后续可替换为真实订单系统。

业务代码只依赖 :class:`OrderSource` 协议，切换订单来源只需修改
``CUSTOMER_SERVICE_ORDER_SOURCE`` 配置：当前仅 ``builtin``（内置演示数据），
真实订单系统（http / postgres）可在此按协议新增后端。
"""

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.logs.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """一张订单。"""

    order_id: str
    status: str
    items: list[str]
    amount: float
    logistics: str
    created_at: str

    def to_text(self) -> str:
        """转为适合大模型阅读的简洁文本。"""
        return (
            f"订单号：{self.order_id}\n"
            f"状态：{self.status}\n"
            f"商品：{', '.join(self.items)}\n"
            f"金额：{self.amount:.2f} 元\n"
            f"物流：{self.logistics}\n"
            f"下单时间：{self.created_at}"
        )


@runtime_checkable
class OrderSource(Protocol):
    """订单查询的统一接口。新来源只需实现本协议并在 :func:`build_order_source` 注册。"""

    async def lookup(self, order_id: str) -> Order | None:
        """按订单号查询订单，未找到返回 None。"""
        ...


# 内置演示订单：用于开发环境与真实订单系统接入前的兜底
_ORDERS: dict[str, Order] = {
    "SO20260901001": Order(
        "SO20260901001",
        "已发货",
        ["轻便透气跑步鞋 x1"],
        299.0,
        "顺丰速运 SF1234567890，已到达杭州转运中心",
        "2026-09-01 10:23",
    ),
    "SO20260902002": Order(
        "SO20260902002",
        "运输中",
        ["智能运动手表 x1"],
        699.0,
        "中通快递 ZT9876543210，运输中，预计 2026-09-05 送达",
        "2026-09-02 14:05",
    ),
    "SO20260903003": Order(
        "SO20260903003",
        "已签收",
        ["运动水杯 x2"],
        98.0,
        "京东物流 JD000111222，已签收",
        "2026-09-03 09:40",
    ),
}


class BuiltinOrderSource(OrderSource):
    """基于内置演示订单的查询，订单号大小写不敏感。"""

    async def lookup(self, order_id: str) -> Order | None:
        return _ORDERS.get(order_id.strip().upper())


def build_order_source(source: str | None = None) -> OrderSource:
    """根据配置创建订单查询源。当前仅支持内置演示订单。"""
    source = source or settings.CUSTOMER_SERVICE_ORDER_SOURCE
    if source != "builtin":
        raise NotImplementedError(f"CUSTOMER_SERVICE_ORDER_SOURCE={source} 尚未实现，请改用 builtin 或接入真实订单系统")
    logger.info("订单查询源：builtin（内置演示订单）")
    return BuiltinOrderSource()
