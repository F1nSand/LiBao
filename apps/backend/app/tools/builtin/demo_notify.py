"""内置工具 tl_demo_notify：发送通知（M2 人工确认流程演示工具）。

require_confirm=True（不可逆/对外副作用操作需确认），用户确认后才真正"发送"。
"""

from __future__ import annotations


def handler(message: str, channel: str = "default") -> dict:
    return {"delivered": True, "message": message, "channel": channel}
