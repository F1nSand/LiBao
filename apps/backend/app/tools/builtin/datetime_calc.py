"""内置工具 tl_datetime_calc：日期/时间计算（纯本地，无需外网）。

op: now（当前日期时间）/ add_days（加/减天数）/ weekday（星期几）/ days_between（两日期间隔天数）。
date 默认今天（YYYY-MM-DD）。异常兜底 error。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

_WEEKDAYS_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _parse_date(value: str | None) -> date:
    if not value:
        return datetime.now(UTC).date()
    return datetime.fromisoformat(value).date()


async def datetime_calc_handler(
    op: str, date: str | None = None, days: int = 0, other: str | None = None
) -> dict[str, Any]:
    """日期计算：{op, date?, days?, other?} → 结构化结果。"""
    try:
        d = _parse_date(date)
        weekday = _WEEKDAYS_ZH[d.weekday()]
        if op == "now":
            now = datetime.now(UTC)
            return {"now": now.isoformat(), "date": now.date().isoformat(), "weekday": weekday}
        if op == "add_days":
            result = d + timedelta(days=days)
            return {"result": result.isoformat(), "weekday": _WEEKDAYS_ZH[result.weekday()]}
        if op == "weekday":
            return {"weekday": weekday, "date": d.isoformat()}
        if op == "days_between":
            other_d = _parse_date(other)
            return {"from": d.isoformat(), "to": other_d.isoformat(), "days": (other_d - d).days}
        return {"error": f"未知操作: {op}（可选 now/add_days/weekday/days_between）"}
    except ValueError as exc:
        return {"error": f"日期参数不合法: {exc}"}
