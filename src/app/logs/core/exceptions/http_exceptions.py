"""HTTP 业务异常的统一出口：转发 ``fastcrud`` 提供的异常类型，供路由层直接使用。"""

from fastcrud.exceptions.http_exceptions import (
    BadRequestException,
    CustomException,
    DuplicateValueException,
    ForbiddenException,
    NotFoundException,
    RateLimitException,
    UnauthorizedException,
    UnprocessableEntityException,
)

__all__ = [
    "BadRequestException",
    "CustomException",
    "DuplicateValueException",
    "ForbiddenException",
    "NotFoundException",
    "RateLimitException",
    "UnauthorizedException",
    "UnprocessableEntityException",
]
