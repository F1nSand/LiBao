"""内置工具 tl_weather：天气查询（wttr.in，免费无 key）。

出站黑名单（Settings.fetch_url_denylist，默认空 = 全放行）——与 fetch_url 同 gate；
transport 注入点（镜像 fetch_url/embeddings）供测试 mock，不碰真实外网。异常兜底 error。
默认不启用（管理员显式开启，seed DB 行可管理）。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import get_settings

_WEATHER_HOST = "wttr.in"
_TIMEOUT_S = 10

_transport: httpx.AsyncBaseTransport | None = None  # 测试注入点（镜像 fetch_url）


async def weather_handler(location: str) -> dict[str, Any]:
    """查天气：location 城市名/拼音/坐标 → 当前温度/天气/湿度/风。默认全放行（除非 wttr.in 在黑名单）。"""
    settings = get_settings()
    if _WEATHER_HOST in settings.fetch_url_denylist:
        return {"error": f"天气服务被出站黑名单拦截（{_WEATHER_HOST}）"}
    try:
        url = f"https://{_WEATHER_HOST}/{quote(location)}?format=j1"
        async with httpx.AsyncClient(transport=_transport, timeout=_TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "agent-backend/0.1"})
        if resp.status_code != 200:
            return {"error": f"天气服务 HTTP {resp.status_code}"}
        data = resp.json()
        cur = (data.get("current_condition") or [{}])[0]
        area = (data.get("nearest_area") or [{}])[0]
        name = ((area.get("areaName") or [{}])[0].get("value")) if area else ""
        return {
            "location": name or location,
            "temp_c": cur.get("temp_C"),
            "temp_f": cur.get("temp_F"),
            "weather": (cur.get("weatherDesc") or [{}])[0].get("value") if cur.get("weatherDesc") else None,
            "humidity": cur.get("humidity"),
            "wind_kmh": cur.get("windspeedKmph"),
            "feels_like_c": cur.get("FeelsLikeC"),
            "source": f"https://{_WEATHER_HOST}/{quote(location)}",
        }
    except Exception as exc:  # noqa: BLE001  天气故障不击穿工具
        return {"error": f"天气查询失败: {str(exc)[:300]}"}
