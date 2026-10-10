"""电商导购智能体的 LangChain 工具封装。

工具只依赖 :class:`ProductSource` 协议（``runtime.get_product_source()``），
因此把商品源从 ``builtin`` 切换到 ``pgvector`` / ``hybrid`` 时无需改动本文件。
"""

from langchain_core.tools import tool

from app.logs.core.agents.ecommerce.runtime import get_product_source
from app.logs.core.config import settings


@tool
async def search_products(
    query: str,
    category: str | None = None,
    budget_min: float | None = None,
    budget_max: float | None = None,
) -> str:
    """按用户需求检索商品，返回候选商品的品类、价格与卖点。

    当用户想买东西、问推荐、比价，或需要先看候选商品再给建议时使用。

    Args:
        query: 用户需求描述，例如「500 元以内的跑鞋」。
        category: 品类过滤，例如「运动鞋」「服饰」「数码」「配件」，不确定时留空。
        budget_min: 预算下限（元），不确定时留空。
        budget_max: 预算上限（元），不确定时留空。
    """
    products = await get_product_source().search(
        query,
        category=category,
        budget_min=budget_min,
        budget_max=budget_max,
        top_k=settings.ECOMMERCE_PRODUCT_TOP_K,
    )
    if not products:
        return "没有检索到符合条件的商品，可以放宽品类或预算后重试。"

    lines = [
        f"{index}. {item.name}（{item.category}）{item.price:.0f} 元 —— {item.description}"
        for index, item in enumerate(products, start=1)
    ]
    return "\n".join(lines)


ecommerce_tools = [search_products]
