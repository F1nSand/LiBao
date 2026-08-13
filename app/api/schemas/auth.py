"""认证 schema（docs 03 §5.1）。"""
from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
