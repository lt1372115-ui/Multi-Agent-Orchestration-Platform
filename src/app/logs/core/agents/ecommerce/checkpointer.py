"""短期记忆 Checkpointer 工厂：按配置创建并处理后端回退。

与长期记忆（``memory``）、商品源（``product``）、窗口策略（``window``）
并列的第四类运行期依赖；单例由 ``runtime`` 统一管理。
"""

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from app.logs.core.config import settings

logger = logging.getLogger(__name__)

_checkpointer: Any | None = None


async def build_checkpointer() -> Any:
    """按配置创建短期记忆 Checkpointer，Postgres 后端缺失时优雅回退。"""
    backend = settings.ECOMMERCE_CHECKPOINT_BACKEND
    if backend == "postgres":
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool
        except ImportError:
            logger.warning("未安装 langgraph-checkpoint-postgres，短期记忆回退进程内 MemorySaver")
            return MemorySaver()
        try:
            sync_url = f"{settings.POSTGRES_SYNC_PREFIX}{settings.POSTGRES_URI}"
            pool = AsyncConnectionPool(sync_url, max_size=20, kwargs={"autocommit": True})
            await pool.open()
            # 类型标注上 AsyncConnectionPool 默认泛型是 tuple_row，运行时由 AsyncPostgresSaver
            # 内部按 dict_row 显式创建 cursor，官方示例同样如此，这里无需处理泛型标注差异。
            # 注意：未安装 langgraph-checkpoint-postgres 时该调用在 mypy 眼中是 Any，
            # 若之后补齐依赖并出现 arg-type 报错，在本行加回 type: ignore[arg-type]。
            saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
            await saver.setup()
            logger.info("短期记忆 Checkpointer：AsyncPostgresSaver（持久化）")
            return saver
        except Exception as exc:
            logger.warning("AsyncPostgresSaver 初始化失败，短期记忆回退进程内 MemorySaver: %s", exc)
            return MemorySaver()
    logger.info("短期记忆 Checkpointer：MemorySaver（进程内）")
    return MemorySaver()


async def get_checkpointer() -> Any:
    """获取短期记忆 Checkpointer 单例（根据配置切换后端，缺失时回退）。"""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = await build_checkpointer()
    return _checkpointer
