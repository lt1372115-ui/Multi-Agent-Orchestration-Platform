import logging
import re
from collections.abc import AsyncGenerator, Callable
from contextlib import _AsyncGeneratorContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import fastapi
import redis.asyncio as redis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.logs.core.config import (
    AppSettings,
    ClientSideCacheSettings,
    CryptSettings,
    DatabaseSettings,
    EnvironmentOption,
    EnvironmentSettings,
    RedisCacheSettings,
    RedisQueueSettings,
    RedisRateLimiterSettings,
    Settings,
    SkipInfraSettings,
    settings,
)
from app.logs.core.db.database import Base, async_engine as engine
from app.logs.core.logger import configure_logging
from app.logs.core.utils import cache, milvus, queue, rag_collections, rate_limit
from app.middleware.client_cache_middleware import ClientCacheMiddleware

logger = logging.getLogger(__name__)


# -------------- 数据库 --------------
async def create_tables() -> None:
    logger.info("正在创建/校验数据库表结构（Base.metadata.create_all）")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库表结构创建/校验完成，连接验证表 connection_test 已就绪")


# -------------- 缓存 --------------
async def create_redis_cache_pool() -> None:
    if settings.SKIP_INFRA_ON_START:
        logger.info("已跳过 Redis 缓存连接（SKIP_INFRA_ON_START=true）")
        return
    logger.info("正在连接 Redis 缓存: %s", settings.REDIS_CACHE_URL)
    cache.pool = redis.ConnectionPool.from_url(settings.REDIS_CACHE_URL)
    cache.client = redis.Redis.from_pool(cache.pool)
    await cache.client.ping()
    logger.info("Redis 缓存连接成功: %s", settings.REDIS_CACHE_URL)


async def close_redis_cache_pool() -> None:
    if cache.client is not None:
        logger.info("正在关闭 Redis 缓存连接")
        await cache.client.aclose()


# -------------- 队列 --------------
async def create_redis_queue_pool() -> None:
    if settings.SKIP_INFRA_ON_START:
        logger.info("已跳过 Redis 队列连接（SKIP_INFRA_ON_START=true）")
        return
    logger.info("正在连接 Redis 队列: %s:%s", settings.REDIS_QUEUE_HOST, settings.REDIS_QUEUE_PORT)
    queue.pool = await create_pool(
        RedisSettings(
            host=settings.REDIS_QUEUE_HOST,
            port=settings.REDIS_QUEUE_PORT,
            password=settings.REDIS_PASSWORD or None,
        )
    )
    logger.info("Redis 队列连接成功: %s:%s", settings.REDIS_QUEUE_HOST, settings.REDIS_QUEUE_PORT)


async def close_redis_queue_pool() -> None:
    if queue.pool is not None:
        logger.info("正在关闭 Redis 队列连接")
        await queue.pool.aclose()


# -------------- 限流 --------------
async def create_redis_rate_limit_pool() -> None:
    if settings.SKIP_INFRA_ON_START:
        logger.info("已跳过 Redis 限流连接（SKIP_INFRA_ON_START=true）")
        return
    logger.info("正在连接 Redis 限流: %s", settings.REDIS_RATE_LIMIT_URL)
    rate_limit.pool = redis.ConnectionPool.from_url(settings.REDIS_RATE_LIMIT_URL)
    rate_limit.client = redis.Redis.from_pool(rate_limit.pool)
    await rate_limit.client.ping()
    logger.info("Redis 限流连接成功: %s", settings.REDIS_RATE_LIMIT_URL)


async def close_redis_rate_limit_pool() -> None:
    if rate_limit.client is not None:
        logger.info("正在关闭 Redis 限流连接")
        await rate_limit.client.aclose()


# -------------- 应用 --------------
async def set_threadpool_tokens(number_of_tokens: int = 100) -> None:
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = number_of_tokens


def _static_version(static_dir: Path) -> str:
    """以静态目录里最新文件的修改时间（秒）作为资源版本号。"""
    try:
        stamp = max(path.stat().st_mtime for path in static_dir.iterdir() if path.is_file())
    except ValueError:
        return "1"
    return str(int(stamp))


def _warn_if_insecure_secret(settings: Settings) -> None:
    """生产环境仍使用模板默认 SECRET_KEY 时告警。

    默认密钥是公开的，任何人都能据此伪造任意用户的 JWT；这里不直接拒绝启动，
    避免把已有的本地/演示环境卡死，但必须把风险显式写进日志。
    """
    if settings.ENVIRONMENT != EnvironmentOption.PRODUCTION:
        return
    default_secret = CryptSettings.model_fields["SECRET_KEY"].default
    if default_secret == settings.SECRET_KEY:
        logger.warning(
            "SECRET_KEY 仍是模板默认值，生产环境必须替换为随机密钥（openssl rand -hex 32），否则 JWT 可被伪造"
        )


def lifespan_factory(
    settings: Settings,
    create_tables_on_start: bool = True,
) -> Callable[[FastAPI], _AsyncGeneratorContextManager[Any]]:
    """创建 FastAPI 的 lifespan 上下文管理器工厂。

    启动时按配置连接数据库 / Redis / Milvus 等基础设施，关闭时逐个释放连接。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        await set_threadpool_tokens()
        configure_logging()
        # Enum 用 %s 会打印成 "EnvironmentOption.LOCAL"，这里取 value 输出可读的 local/staging/production
        logger.info("应用启动，环境=%s，日志级别=%s", settings.ENVIRONMENT.value, settings.LOG_LEVEL)
        _warn_if_insecure_secret(settings)

        if (
            isinstance(settings, DatabaseSettings)
            and create_tables_on_start
            and not (isinstance(settings, SkipInfraSettings) and settings.SKIP_INFRA_ON_START)
        ):
            await create_tables()

        if isinstance(settings, RedisCacheSettings):
            await create_redis_cache_pool()

        if isinstance(settings, RedisQueueSettings):
            await create_redis_queue_pool()

        if isinstance(settings, RedisRateLimiterSettings):
            await create_redis_rate_limit_pool()

        if settings.ENABLE_MILVUS:
            await anyio.to_thread.run_sync(milvus.connect)
            if settings.AUTO_CREATE_RAG_COLLECTIONS:
                client = milvus.get_client()
                if client is not None:
                    try:
                        created = await anyio.to_thread.run_sync(rag_collections.ensure_collections, client)
                        if created:
                            logger.info("本次新建 Milvus 集合: %s", created)
                    except Exception as exc:
                        logger.warning("Milvus RAG 集合创建失败: %s", exc)
            else:
                logger.info("已跳过 Milvus RAG 集合自动创建（AUTO_CREATE_RAG_COLLECTIONS=false）")

        yield

        if isinstance(settings, RedisCacheSettings):
            await close_redis_cache_pool()

        if isinstance(settings, RedisQueueSettings):
            await close_redis_queue_pool()

        if isinstance(settings, RedisRateLimiterSettings):
            await close_redis_rate_limit_pool()

        if settings.ENABLE_MILVUS:
            await anyio.to_thread.run_sync(milvus.close)

    return lifespan


# -------------- 应用 --------------
def create_application(
    router: APIRouter,
    settings: Settings,
    create_tables_on_start: bool = True,
    **kwargs: Any,
) -> FastAPI:
    """按配置创建并组装 FastAPI 应用。

    顶层 ``Settings`` 同时继承多个配置子类，命中哪一类就装配对应的能力：

    - ``AppSettings``：写入应用元信息（名称、描述、联系人、许可证）。
    - ``DatabaseSettings``：启动时建表 / 校验表结构。
    - ``RedisCacheSettings`` / ``RedisQueueSettings`` / ``RedisRateLimiterSettings``：
      分别建立并释放缓存、队列、限流连接池。
    - ``ClientSideCacheSettings``：挂载客户端缓存中间件。
    - ``EnvironmentSettings``：按环境决定交互式文档（``/docs``、``/redoc``）是否开放。

    Args:
        router: 需要挂载的路由（本项目为 ``/api`` 聚合路由）。
        settings: 顶层配置对象 ``Settings``。
        create_tables_on_start: 启动时是否建表，默认 ``True``。
        **kwargs: 透传给 FastAPI 构造函数的额外参数。

    Returns:
        配置完成的 FastAPI 应用实例。
    """
    # --- 装配应用元信息（在创建应用之前） ---
    if isinstance(settings, AppSettings):
        to_update = {
            "title": settings.APP_NAME,
            "description": settings.APP_DESCRIPTION,
            "contact": {"name": settings.CONTACT_NAME, "email": settings.CONTACT_EMAIL},
            "license_info": {"name": settings.LICENSE_NAME},
        }
        kwargs.update(to_update)

    if isinstance(settings, EnvironmentSettings):
        kwargs.update({"docs_url": None, "redoc_url": None, "openapi_url": None})

    lifespan = lifespan_factory(settings, create_tables_on_start=create_tables_on_start)

    application = FastAPI(lifespan=lifespan, **kwargs)
    application.include_router(router)

    # 托管前端页面：访问 / 打开出行简报页面，静态资源放在 /static 下
    # 静态目录位于 src/app/static，因此从 core 目录向上 2 层
    static_dir = Path(__file__).resolve().parents[2] / "static"
    if static_dir.is_dir():
        application.mount("/static", StaticFiles(directory=static_dir), name="static")

        def render_page(html_path: Path, version_dir: Path) -> Response:
            """读取页面 HTML，并把静态资源版本号替换成文件修改时间。

            前端文件一改动 ``?v=`` 就自动变化，浏览器不会再命中旧脚本，
            也就不需要手动去改 index.html 里的版本号。
            """

            html = html_path.read_text(encoding="utf-8")
            return Response(
                content=re.sub(r"\?v=\d+", f"?v={_static_version(version_dir)}", html),
                media_type="text/html",
            )

        @application.get("/", include_in_schema=False)
        async def agent_hub() -> Response:
            """返回多智能体导航首页。"""
            return render_page(static_dir / "portal.html", static_dir)

        @application.get("/weather", include_in_schema=False)
        async def weather_agent_page() -> Response:
            """天气智能体 · 出行简报页。"""
            return render_page(static_dir / "index.html", static_dir)

        @application.get("/ecommerce", include_in_schema=False)
        async def ecommerce_agent_page() -> Response:
            """电商导购智能体 · 带长期记忆的客服页。"""
            return render_page(static_dir / "ecommerce.html", static_dir)

        @application.get("/orchestrator", include_in_schema=False)
        async def orchestrator_agent_page() -> Response:
            """多智能体编排器 · 单入口对话页（LangGraph supervisor）。"""
            return render_page(static_dir / "orchestrator.html", static_dir)

        @application.get("/customer_service", include_in_schema=False)
        async def customer_service_agent_page() -> Response:
            """客服智能体 · 订单查询、退换货与常见问题。"""
            return render_page(static_dir / "customer_service.html", static_dir)

        @application.get("/analyst", include_in_schema=False)
        async def analyst_agent_page() -> Response:
            """分析智能体 · 生成运营日报与经营指标分析。"""
            return render_page(static_dir / "analyst.html", static_dir)

        # 钉协助手智能体：助手页与操作台页，两个页面用顶部菜单互相切换
        dingtalk_dir = static_dir / "dingtalk"
        if dingtalk_dir.is_dir():

            @application.get("/dingtalk", include_in_schema=False)
            async def dingtalk_assistant_page() -> Response:
                """钉协助手智能体 · 助手页（用自然语言指挥钉钉操作）。"""
                return render_page(dingtalk_dir / "index.html", dingtalk_dir)

            @application.get("/dingtalk/console", include_in_schema=False)
            async def dingtalk_console_page() -> Response:
                """钉协助手智能体 · 操作台页（逐个调用钉钉接口）。"""
                return render_page(dingtalk_dir / "console.html", dingtalk_dir)

    if isinstance(settings, ClientSideCacheSettings):
        application.add_middleware(ClientCacheMiddleware, max_age=settings.CLIENT_CACHE_MAX_AGE)  # type: ignore[arg-type]

    if isinstance(settings, EnvironmentSettings):
        if settings.ENVIRONMENT != EnvironmentOption.PRODUCTION:
            docs_router = APIRouter()

            @docs_router.get("/docs", include_in_schema=False)
            async def get_swagger_documentation() -> fastapi.responses.HTMLResponse:
                return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")

            @docs_router.get("/redoc", include_in_schema=False)
            async def get_redoc_documentation() -> fastapi.responses.HTMLResponse:
                return get_redoc_html(openapi_url="/openapi.json", title="docs")

            @docs_router.get("/openapi.json", include_in_schema=False)
            async def openapi() -> dict[str, Any]:
                out: dict = get_openapi(title=application.title, version=application.version, routes=application.routes)
                return out

            application.include_router(docs_router)

        return application

    return application
