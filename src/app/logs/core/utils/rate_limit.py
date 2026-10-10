"""Redis 计数器限流：按「用户 + 路径 + 固定时间窗」累计请求次数。

窗口长度由调用方传入，计数键在窗口结束后自然过期，因此不需要额外的清理任务。
"""

import logging
from datetime import UTC, datetime

from redis.asyncio import ConnectionPool, Redis
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

pool: ConnectionPool | None = None
client: Redis | None = None


def sanitize_path(path: str) -> str:
    """把 URL 路径转成适合拼进 Redis key 的形式（去掉首尾斜杠、斜杠换成下划线）。"""
    return path.strip("/").replace("/", "_")


async def is_rate_limited(db: AsyncSession, user_id: int, path: str, limit: int, period: int) -> bool:
    """按固定时间窗统计请求次数，超出 ``limit`` 时返回 ``True``。

    Args:
        db: 数据库会话（保留参数，便于后续把计数落库）。
        user_id: 限流维度（用户 id）。
        path: 被访问的 URL 路径。
        limit: 单个窗口允许的最大请求数。
        period: 窗口长度（秒）。

    Raises:
        RuntimeError: Redis 客户端未初始化（未启用缓存/限流基础设施）。
    """
    if client is None:
        logger.error("Redis 客户端未初始化，无法执行限流检查")
        raise RuntimeError("Redis 客户端未初始化")

    current_timestamp = int(datetime.now(UTC).timestamp())
    window_start = current_timestamp - (current_timestamp % period)

    sanitized_path = sanitize_path(path)
    key = f"ratelimit:{user_id}:{sanitized_path}:{window_start}"

    try:
        current_count = await client.incr(key)
        if current_count == 1:
            await client.expire(key, period)

        if current_count > limit:
            logger.warning("触发限流: user=%s path=%s count=%s limit=%s", user_id, path, current_count, limit)
            return True
        logger.debug("限流计数: user=%s path=%s count=%s limit=%s", user_id, path, current_count, limit)

    except Exception:
        logger.exception("限流检查失败: user=%s path=%s", user_id, path)
        raise

    return False
