"""内置工具注册。M1：tl_time_now；M2：tl_demo_notify（人工确认流程演示）。"""
from __future__ import annotations

from app.tools.builtin import demo_notify, time_now
from app.tools.registry import SandboxLevel, ToolSpec, ToolType, get, register


def register_builtin_tools() -> None:
    # 幂等引导：已注册则跳过（registry.register 本身仍拒绝覆盖同名工具，防遮蔽）
    if get("tl_time_now") is not None:
        return
    register(
        ToolSpec(
            id="tl_time_now",
            name="time_now",
            description=(
                "获取当前时间。需要知道\"现在几点\"或当前日期时使用，返回 iso/local/tz。"
                "反例：不要用它回答历史日期或无关问题。"
            ),
            params_schema={"type": "object", "properties": {}, "required": []},
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=True,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=time_now.handler,
        )
    )
    register(
        ToolSpec(
            id="tl_demo_notify",
            name="demo_notify",
            description=(
                "发送一条通知消息。用于演示人工确认流程；发送为不可逆/对外副作用操作，"
                "需要用户确认后才真正执行。反例：不要用它回答时间或无关问题。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "通知内容"},
                    "channel": {"type": "string", "description": "发送渠道，默认 default"},
                },
                "required": ["message"],
            },
            tool_type=ToolType.USER_COMMS,
            enabled=True,
            require_confirm=True,
            idempotent=True,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=demo_notify.handler,
        )
    )
