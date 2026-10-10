"""长期记忆包：统一暴露记忆数据载体、存储协议与共用工具函数。

业务代码统一 ``from app.logs.core.agents.ecommerce.memory import ...``，
具体后端（``inmemory`` / ``postgres``）由 :func:`build_memory_store` 按配置创建。
"""

from app.logs.core.agents.ecommerce.memory.base import (
    CLEAR,
    MemoryItem,
    MemoryRecord,
    MemoryStore,
    UserProfile,
    build_memory_store,
    combine_score,
    compute_base_score,
    merge_profile_fields,
    tokenize,
)

__all__ = [
    "CLEAR",
    "MemoryItem",
    "MemoryRecord",
    "MemoryStore",
    "UserProfile",
    "build_memory_store",
    "combine_score",
    "compute_base_score",
    "merge_profile_fields",
    "tokenize",
]
