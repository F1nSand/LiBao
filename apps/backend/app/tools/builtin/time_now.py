"""内置工具 tl_time_now：返回当前时间（《02》后端设计 §7；只读/确定性/幂等/无 confirm）。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def handler() -> dict:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.tz))
    return {
        "iso": now.isoformat(),
        "local": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "tz": settings.tz,
    }
