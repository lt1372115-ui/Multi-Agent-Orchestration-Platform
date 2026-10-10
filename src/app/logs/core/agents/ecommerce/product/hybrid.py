"""混合商品检索：优先向量 RAG，结果不足或不可用时回退内置目录。

两种来源同时可用时合并去重，实现「商品库 + RAG 都支持」。
"""

import logging

from app.logs.core.agents.ecommerce.product.base import Product, ProductSource
from app.logs.core.agents.ecommerce.product.builtin import BuiltinProductSource
from app.logs.core.agents.ecommerce.product.pgvector import PgvectorProductSource

logger = logging.getLogger(__name__)


class HybridProductSource(ProductSource):
    """RAG + 内置目录的组合检索源。"""

    def __init__(self) -> None:
        self._rag = PgvectorProductSource()
        self._builtin = BuiltinProductSource()

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        budget_min: float | None = None,
        budget_max: float | None = None,
        top_k: int = 5,
    ) -> list[Product]:
        merged: list[Product] = []
        seen: set[str] = set()

        # 1. 优先 RAG（向量语义检索）
        # RAG 不可用（未配置 embedding、数据库未装 pgvector、vectors 为空等）时不能把
        # 整次检索打挂：降级为纯内置目录，符合本类「结果不足或不可用就兜底」的约定。
        try:
            rag_products = await self._rag.search(
                query,
                category=category,
                budget_min=budget_min,
                budget_max=budget_max,
                top_k=top_k,
            )
        except Exception as exc:
            logger.warning("向量检索不可用，本次回退内置商品目录：%s", exc)
            rag_products = []
        for product in rag_products:
            if product.id not in seen:
                seen.add(product.id)
                merged.append(product)

        # 2. 不足时用内置目录兜底（关键词检索）
        if len(merged) < top_k:
            builtin_products = await self._builtin.search(
                query,
                category=category,
                budget_min=budget_min,
                budget_max=budget_max,
                top_k=top_k - len(merged),
            )
            for product in builtin_products:
                if product.id not in seen:
                    seen.add(product.id)
                    merged.append(product)

        merged.sort(key=lambda item: item.score, reverse=True)
        return merged[:top_k]
