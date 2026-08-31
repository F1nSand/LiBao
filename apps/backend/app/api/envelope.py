"""REST 统一信封 {code, message, data, trace_id}（《02》接口契约 §2.1）。"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_trace_id


def ok(data: Any = None, trace_id: str | None = None) -> dict[str, Any]:
    return {"code": 0, "message": "ok", "data": data, "trace_id": trace_id or get_trace_id()}


def fail(code: int, message: str, trace_id: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "data": None, "trace_id": trace_id or get_trace_id()}
