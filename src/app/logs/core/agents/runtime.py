"""智能体运行期单例：短期记忆窗口策略与长期记忆存储。

与 :mod:`app.logs.core.agents.window` 分离：``window`` 模块负责策略实现细节，
本模块负责窗口策略与长期记忆存储的单例持有与懒加载，避免模块导入期就执行配置读取。
"""

from app.logs.core.agents.ecommerce.memory.base import MemoryStore, build_memory_store
from app.logs.core.agents.window import WindowStrategy, build_window_strategy

_window: WindowStrategy | None = None
_store: MemoryStore | None = None


def get_window_strategy() -> WindowStrategy:
    """获取短期记忆窗口管理策略单例（根据配置切换策略）。"""
    global _window
    if _window is None:
        _window = build_window_strategy()
    return _window


def get_memory_store() -> MemoryStore:
    """获取长期记忆存储单例（根据配置切换后端）。"""
    global _store
    if _store is None:
        _store = build_memory_store()
    return _store
