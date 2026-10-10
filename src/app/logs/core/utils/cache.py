"""FastAPI 接口缓存工具：缓存 GET 响应，并在写操作时失效相关缓存。

缓存键形如 ``{key_prefix 渲染结果}:{resource_id}``，读写通过 Redis 完成；
Redis 客户端由应用生命周期（``core/setup.py``）注入到本模块的 ``client``。
"""

import functools
import json
import logging
import re
from collections.abc import Callable
from typing import Any, cast

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from redis.asyncio import ConnectionPool, Redis

from app.logs.core.exceptions.cache_exceptions import (
    CacheIdentificationInferenceError,
    InvalidRequestError,
    MissingClientError,
)

logger = logging.getLogger(__name__)

pool: ConnectionPool | None = None
client: Redis | None = None


def _infer_resource_id(kwargs: dict[str, Any], resource_id_type: type | tuple[type, ...]) -> int | str:
    """从关键字参数中推断资源 id（用于拼接缓存键）。

    Args:
        kwargs: 被装饰函数的全部关键字参数。
        resource_id_type: 期望的资源 id 类型，``int`` 或 ``str``（也接受类型元组）。

    Raises:
        CacheIdentificationInferenceError: 没能从参数中推断出符合类型的资源 id。
    """
    resource_id: int | str | None = None
    for arg_name, arg_value in kwargs.items():
        if isinstance(arg_value, resource_id_type):
            if (resource_id_type is int) and ("id" in arg_name):
                resource_id = cast(int, arg_value)

            elif (resource_id_type is int) and ("id" not in arg_name):
                pass

            elif resource_id_type is str:
                resource_id = cast(str, arg_value)

    if resource_id is None:
        raise CacheIdentificationInferenceError

    return resource_id


def _extract_data_inside_brackets(input_string: str) -> list[str]:
    """取出字符串中 ``{...}`` 占位符的名字。

    例：``"The {quick} brown {fox}"`` → ``["quick", "fox"]``。
    """
    return re.findall(r"{(.*?)}", input_string)


def _construct_data_dict(data_inside_brackets: list[str], kwargs: dict[str, Any]) -> dict[str, Any]:
    """按占位符名字从 ``kwargs`` 中取值，组成模板渲染所需的字典。"""
    data_dict = {}
    for key in data_inside_brackets:
        data_dict[key] = kwargs[key]
    return data_dict


def _format_prefix(prefix: str, kwargs: dict[str, Any]) -> str:
    """用 ``kwargs`` 渲染带 ``{参数名}`` 占位符的模板字符串。

    例：``_format_prefix("user_{user_id}", {"user_id": 7})`` → ``"user_7"``。
    """
    data_inside_brackets = _extract_data_inside_brackets(prefix)
    data_dict = _construct_data_dict(data_inside_brackets, kwargs)
    return prefix.format(**data_dict)


def _format_extra_data(to_invalidate_extra: dict[str, str], kwargs: dict[str, Any]) -> dict[str, Any]:
    """把「关联缓存模板」渲染成 ``{渲染后的前缀: 资源 id 值}``。

    ``to_invalidate_extra`` 形如 ``{"user_items": "{user_id}"}``：
    键是缓存前缀模板，值是该前缀使用的资源 id 占位符。
    """
    formatted_extra = {}
    for prefix, id_template in to_invalidate_extra.items():
        formatted_prefix = _format_prefix(prefix, kwargs)
        resource_id = _extract_data_inside_brackets(id_template)[0]
        formatted_extra[formatted_prefix] = kwargs[resource_id]

    return formatted_extra


async def _delete_keys_by_pattern(pattern: str) -> None:
    """用 ``SCAN`` 游标批量删除匹配 ``pattern`` 的缓存键。

    相比 ``KEYS``，``SCAN`` 不会长时间阻塞 Redis；每批取 100 个键后批量删除，
    直到没有匹配键为止。``pattern`` 命中范围过大时开销较高，需谨慎使用。
    """
    if client is None:
        raise MissingClientError

    cursor = -1
    while cursor != 0:
        cursor, keys = await client.scan(cursor, match=pattern, count=100)
        if keys:
            await client.delete(*keys)


def cache(
    key_prefix: str,
    resource_id_name: Any = None,
    expiration: int = 3600,
    resource_id_type: type | tuple[type, ...] = int,
    to_invalidate_extra: dict[str, Any] | None = None,
    pattern_to_invalidate_extra: list[str] | None = None,
) -> Callable:
    """FastAPI 接口缓存装饰器。

    GET 请求命中缓存时直接返回缓存内容，未命中则执行原函数并把结果写回缓存；
    非 GET 请求执行原函数后失效对应缓存，可额外失效关联缓存与按前缀批量失效的缓存。

    用法：把 ``@cache(key_prefix="user_items", resource_id_name="user_id")`` 加在
    GET 路由函数上；写接口用 ``to_invalidate_extra={"user_items": "{user_id}"}``
    让写操作自动失效对应缓存。

    Args:
        key_prefix: 缓存键前缀模板，可用 ``{参数名}`` 引用被装饰函数的参数。
        resource_id_name: 资源 id 的参数名；不传则按 ``resource_id_type`` 自动推断。
        expiration: 缓存过期时间（秒），默认 3600。
        resource_id_type: 自动推断资源 id 时接受的类型，默认 ``int``。
        to_invalidate_extra: 写操作时需一并失效的关联缓存，形如 ``{"user_items": "{user_id}"}``。
        pattern_to_invalidate_extra: 写操作时按前缀批量失效的键模式列表。

    Raises:
        MissingClientError: Redis 客户端未初始化。
        InvalidRequestError: GET 请求上使用了只对写操作有意义的失效参数。

    Note:
        ``resource_id_type`` 仅在未传 ``resource_id_name`` 时生效；
        ``pattern_to_invalidate_extra`` 会扫描键空间，数据量大时开销较高。
    """

    def wrapper(func: Callable) -> Callable:
        @functools.wraps(func)
        async def inner(request: Request, *args: Any, **kwargs: Any) -> Response:
            if client is None:
                raise MissingClientError

            if resource_id_name:
                resource_id = kwargs[resource_id_name]
            else:
                resource_id = _infer_resource_id(kwargs=kwargs, resource_id_type=resource_id_type)

            formatted_key_prefix = _format_prefix(key_prefix, kwargs)
            cache_key = f"{formatted_key_prefix}:{resource_id}"
            if request.method == "GET":
                if to_invalidate_extra is not None or pattern_to_invalidate_extra is not None:
                    raise InvalidRequestError

                cached_data = await client.get(cache_key)
                if cached_data:
                    logger.debug("缓存命中: %s", cache_key)
                    return cast(Response, json.loads(cached_data.decode()))
                logger.debug("缓存未命中: %s", cache_key)

            result = await func(request, *args, **kwargs)

            if request.method == "GET":
                serializable_data = jsonable_encoder(result)
                serialized_data = json.dumps(serializable_data)

                await client.set(cache_key, serialized_data)
                await client.expire(cache_key, expiration)
                logger.debug("写入缓存: %s（过期 %s 秒）", cache_key, expiration)

                serialized_data = json.loads(serialized_data)

            else:
                await client.delete(cache_key)
                logger.debug("失效缓存: %s", cache_key)
                if to_invalidate_extra is not None:
                    formatted_extra = _format_extra_data(to_invalidate_extra, kwargs)
                    for prefix, resource_id in formatted_extra.items():
                        extra_cache_key = f"{prefix}:{resource_id}"
                        await client.delete(extra_cache_key)
                        logger.debug("失效关联缓存: %s", extra_cache_key)

                if pattern_to_invalidate_extra is not None:
                    for pattern in pattern_to_invalidate_extra:
                        formatted_pattern = _format_prefix(pattern, kwargs)
                        await _delete_keys_by_pattern(formatted_pattern + "*")

            return cast(Response, result)

        return inner

    return wrapper
