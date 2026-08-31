"""SSE 事件构造（《02》接口契约 §3：信封 {id, seq, type, ts, payload}；ts 为 epoch 毫秒）。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

SSE_EVENT_TYPES = (
    "message_start",
    "message",  # 逐轮消息封口（《02》接口契约 §3 多消息扩展）：每非最终轮工具结果齐后发射
    "token",
    "tool_call",
    "tool_result",
    "agent_switch",
    "status",
    "interrupt",
    "done",
    "error",
    "notification",
)


def make_event(event_type: str, payload: dict[str, Any], seq: int, *, task_seq: int | None = None) -> dict[str, Any]:
    event = {
        "id": f"evt_{seq}",
        "seq": seq,
        "type": event_type,
        "ts": int(time.time() * 1000),
        "payload": payload,
    }
    if task_seq is not None:
        event["task_seq"] = task_seq
        event["id"] = f"task_evt_{task_seq}"
    return event


def format_sse(env: dict[str, Any]) -> str:
    """单条 SSE 帧：event: <type>\\ndata: <envelope json>\\n\\n"""
    return f"event: {env['type']}\ndata: {json.dumps(env, ensure_ascii=False)}\n\n"


def sse_emitter() -> Callable[[str, dict[str, Any]], str]:
    """SSE 帧发射器（seq 单调从 1 起，《02》接口契约 §3.2）。各流式入口共用，避免重复闭包。"""
    seq = 0

    def emit(event_type: str, payload: dict[str, Any]) -> str:
        nonlocal seq
        seq += 1
        return format_sse(make_event(event_type, payload, seq))

    return emit
