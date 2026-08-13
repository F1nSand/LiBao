"""系统路由（docs 03 §5.8）。M1 仅 health。"""
from __future__ import annotations

import time

from fastapi import APIRouter

from app.api.envelope import ok
from app.core.config import get_settings

router = APIRouter()


@router.get("/system/health")
async def health():
    settings = get_settings()
    return ok({"status": "ok", "service": "agent-backend", "env": settings.app_env, "time": int(time.time())})
