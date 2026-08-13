"""认证与权限（docs 01 §2 core/security.py，docs 00 原则：模型不能自证完成）。

JWT：HS256，payload 必须含 role（前端 parseRole 依赖，FrontEnd/src/utils/token.ts）。
密码：bcrypt 直接哈希（不使用 passlib——其与 bcrypt>=4.1 存在 __about__ 冲突）。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import bcrypt
import jwt

from app.core.config import get_settings


class TokenUser(Protocol):
    """create_access_token 的入参最小协议（不耦合 storage 模型）。"""

    id: uuid.UUID
    role: str
    org_id: uuid.UUID
    name: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user: TokenUser) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "role": user.role,
        "org_id": str(user.org_id),
        "name": user.name,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
