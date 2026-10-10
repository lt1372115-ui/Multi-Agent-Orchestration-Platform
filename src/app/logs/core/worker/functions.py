"""ARQ worker 的启动/关闭钩子与示例后台任务。"""

import asyncio
import logging

from arq.worker import Worker

try:  # uvloop 仅支持非 Windows 平台，Windows 下回退到标准事件循环
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

logger = logging.getLogger(__name__)


# -------- background tasks --------
async def sample_background_task(ctx: Worker, name: str) -> str:
    """示例后台任务：等待 5 秒后返回完成信息。"""
    await asyncio.sleep(5)
    return f"Task {name} is complete!"


# -------- base functions --------
async def startup(ctx: Worker) -> None:
    """ARQ worker 启动钩子。"""
    logger.info("ARQ worker 已启动")


async def shutdown(ctx: Worker) -> None:
    """ARQ worker 关闭钩子。"""
    logger.info("ARQ worker 已停止")
