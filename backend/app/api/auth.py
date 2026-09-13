"""认证：admin 密码登录 + JWT（D48）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from passlib.context import CryptContext

from app.configs.settings import get_settings
from app.models.schemas import fail, ok

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(pw: str) -> str:
    return pwd_context.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    return pwd_context.verify(pw, hashed)


def create_token(username: str) -> str:
    s = get_settings()
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expire_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> str:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=["HS256"])["sub"]
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Token 无效或过期") from exc


@router.post("/login")
def login(body: dict):
    s = get_settings()
    pw = body.get("password", "")
    # 单账号：固定 admin；生产建议存哈希于 settings/DB（此处用 env 默认）
    if not verify_password(pw, hash_password(s.admin_password)):
        return fail("AUTH_FAILED", "密码错误")
    token = create_token("admin")
    return ok({"token": token, "expires_in": s.jwt_expire_minutes * 60})


@router.post("/logout")
def logout(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "") if authorization else ""
    decode_token(token)
    return ok("已登出")


@router.get("/verify")
def verify(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "") if authorization else ""
    username = decode_token(token)
    return ok({"username": username})