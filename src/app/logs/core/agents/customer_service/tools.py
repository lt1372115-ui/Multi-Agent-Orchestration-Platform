"""客服智能体的 LangChain 工具封装，供 Agent 调用。"""

from langchain_core.tools import tool

from app.logs.core.agents.customer_service.after_sale import ReturnRequest, build_return_source
from app.logs.core.agents.customer_service.order import Order, build_order_source


@tool
async def lookup_order(order_id: str) -> str:
    """查询指定订单号的订单详情与物流状态。

    当用户提供订单号，询问订单状态、发货/物流进度、是否已签收、退款进度时使用。

    Args:
        order_id: 订单号，例如「SO20260901001」。
    """
    order: Order | None = await build_order_source().lookup(order_id)
    if order is None:
        return f"未查询到订单「{order_id}」，请核对订单号后重试。"
    return str(order.to_text())


@tool
async def apply_return(order_id: str, action: str, reason: str) -> str:
    """为用户提交退换货申请（退货或换货）。

    当用户表示想退货、换货、申请退换货或退款退货时使用。提交前建议先用
    lookup_order 确认订单存在；本工具内部也会校验订单号，找不到订单会返回提示。

    Args:
        order_id: 订单号，例如「SO20260901001」。
        action: 退换货类型，只能是「退货」或「换货」。
        reason: 退换货原因，例如「商品尺码不合适」「不喜欢」「质量问题」。
    """
    request: ReturnRequest | None = await build_return_source().apply(order_id, action, reason)
    if request is None:
        return f"未查询到订单「{order_id}」，无法提交退换货申请，请核对订单号后重试。"
    return str(request.to_text())


customer_service_tools = [lookup_order, apply_return]
