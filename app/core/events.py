"""SSE 事件构造（docs 03 §3：信封 {id, seq, type, ts, payload}；ts 为 epoch 毫秒）。"""
from __future__ import annotations

import json
import time
from typing import Any

SSE_EVENT_TYPES = (
    "message_start",
    "token",
    "tool_call",
    "tool_result",
    "agent_switch",
    "status",
    "interrupt",
    "done",
    "error",
)


def make_event(event_type: str, payload: dict[str, Any], seq: int) -> dict[str, Any]:
    return {
        "id": f"evt_{seq}",
        "seq": seq,
        "type": event_type,
        "ts": int(time.time() * 1000),
        "payload": payload,
    }


def format_sse(env: dict[str, Any]) -> str:
    """单条 SSE 帧：event: <type>\\ndata: <envelope json>\\n\\n"""
    return f"event: {env['type']}\ndata: {json.dumps(env, ensure_ascii=False)}\n\n"
