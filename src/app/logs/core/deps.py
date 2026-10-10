"""FastAPI 公共依赖：认证。"""

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.logs.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    """从 Bearer 令牌解析当前登录用户 id（整型）。"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    try:
        return int(decode_access_token(credentials.credentials))
    except (ValueError, pyjwt.PyJWTError) as exc:
        raise HTTPException(status_code=401, detail="认证令牌无效或已过期") from exc
