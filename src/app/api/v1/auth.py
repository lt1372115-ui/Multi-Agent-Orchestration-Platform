"""认证接口：注册与登录。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.logs.core.db import User
from app.logs.core.db.database import local_session
from app.logs.core.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["认证模块"])


class RegisterRequest(BaseModel):
    """注册请求体。"""

    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6, max_length=128)


class TokenResponse(BaseModel):
    """令牌响应体。"""

    access_token: str
    token_type: str = "bearer"
    user_id: int


@router.post("/register", summary="注册新用户")
async def register(request: RegisterRequest) -> TokenResponse:
    """注册用户并直接返回访问令牌。"""
    async with local_session() as session:
        exists = await session.scalar(select(User.id).where(User.username == request.username))
        if exists:
            raise HTTPException(status_code=409, detail="用户名已存在")
        user = User(username=request.username, password_hash=hash_password(request.password))
        session.add(user)
        try:
            await session.commit()
        except IntegrityError as exc:
            # 并发注册同名用户时会撞上 username 唯一约束：回滚并把冲突映射成 409，
            # 而不是把 IntegrityError 冒泡成 500。
            await session.rollback()
            raise HTTPException(status_code=409, detail="用户名已存在") from exc
        await session.refresh(user)
        return TokenResponse(
            access_token=create_access_token(str(user.id)),
            user_id=user.id,
        )


@router.post("/login", summary="用户登录")
async def login(request: LoginRequest) -> TokenResponse:
    """校验用户名密码并返回访问令牌。"""
    async with local_session() as session:
        user = await session.scalar(select(User).where(User.username == request.username))
        if user is None or not verify_password(request.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="账号已被禁用")
        return TokenResponse(
            access_token=create_access_token(str(user.id)),
            user_id=user.id,
        )
