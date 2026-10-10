from collections.abc import Callable
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.logs.core.config import settings
from app.logs.core.worker.functions import sample_background_task, shutdown, startup

REDIS_QUEUE_HOST = settings.REDIS_QUEUE_HOST
REDIS_QUEUE_PORT = settings.REDIS_QUEUE_PORT
REDIS_PASSWORD = settings.REDIS_PASSWORD or None


class WorkerSettings:
    """ARQ worker 配置：任务注册表、Redis 连接与生命周期钩子。"""

    functions: ClassVar[list[Callable[..., Any]]] = [sample_background_task]
    # Redis 开启 requirepass 时必须带上密码，否则 worker 连不上队列
    redis_settings = RedisSettings(host=REDIS_QUEUE_HOST, port=REDIS_QUEUE_PORT, password=REDIS_PASSWORD)
    on_startup = startup
    on_shutdown = shutdown
    handle_signals = False
