"""电商导购智能体的运行期单例：商品检索源。

独立成模块以避免 ``agent`` 与 ``tools`` 之间的循环导入，
两者都从这里按配置获取单例；短期记忆窗口策略与长期记忆存储的单例
统一放在 :mod:`app.logs.core.agents.runtime`。
"""

from app.logs.core.agents.ecommerce.product.base import ProductSource, build_product_source

_source: ProductSource | None = None


def get_product_source() -> ProductSource:
    """获取商品检索源单例（根据配置切换后端）。"""
    global _source
    if _source is None:
        _source = build_product_source()
    return _source
