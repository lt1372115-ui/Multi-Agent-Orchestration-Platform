"""应用日志配置：控制台输出 + 按大小滚动的文件输出（``src/app/logs/app.log``）。

由应用启动流程显式调用 :func:`configure_logging`，不依赖模块导入副作用，
这样日志初始化的时机可控、也便于测试。
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.logs.core.config import settings

# 本文件位于 src/app/logs/core/logger.py，日志目录取上一级的 src/app/logs
LOG_DIR = Path(__file__).resolve().parents[1]
LOG_FILE_PATH = LOG_DIR / "app.log"
LOGGING_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _resolve_level() -> int:
    """把配置中的日志级别名解析成 logging 级别，非法取值回退 INFO。"""
    return getattr(logging, str(settings.LOG_LEVEL).upper(), logging.INFO)


def configure_logging() -> None:
    """初始化日志：设置 root logger 级别并挂载滚动文件 handler（幂等）。

    - 控制台输出沿用 ``logging.basicConfig``，已有日志配置时不会重复添加 handler。
    - 文件 handler 不在自身设级别，交给 root logger 统一过滤：否则 ``LOG_LEVEL=DEBUG``
      时控制台能看到调试日志、文件里却收不到。
    - 重复调用（多次启动、测试）不会重复挂载同一个文件 handler。
    """
    level = _resolve_level()
    logging.basicConfig(level=level, format=LOGGING_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    target = str(LOG_FILE_PATH)
    if any(
        isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == target
        for handler in root_logger.handlers
    ):
        return

    file_handler = RotatingFileHandler(LOG_FILE_PATH, maxBytes=10485760, backupCount=5)
    file_handler.setLevel(logging.NOTSET)
    file_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
    root_logger.addHandler(file_handler)
