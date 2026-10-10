from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class ClientCacheMiddleware(BaseHTTPMiddleware):
    """为响应补上客户端缓存头 ``Cache-Control`` 的中间件。

    Args:
        app: FastAPI 应用实例。
        max_age: 客户端可缓存的最大秒数，默认 60 秒。

    Attributes:
        max_age: 客户端可缓存的最大秒数。

    Note:
        只在路由未显式设置 ``Cache-Control`` 时才补默认值，
        以免覆盖 SSE 等流式接口已经声明的 ``no-cache``。
    """

    def __init__(self, app: FastAPI, max_age: int = 60) -> None:
        super().__init__(app)
        self.max_age = max_age

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """处理单次请求：必要时补上 ``Cache-Control`` 头后返回响应。

        由 Starlette 在请求-响应周期的外层自动调用。
        """
        response: Response = await call_next(request)
        if "cache-control" not in response.headers:
            response.headers["Cache-Control"] = f"public, max-age={self.max_age}"
        return response
