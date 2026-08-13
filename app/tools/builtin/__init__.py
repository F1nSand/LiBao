"""内置工具注册（M1 唯一工具 tl_time_now）。M2 起工具 CRUD 由 tool_definition 表驱动。"""
from __future__ import annotations

from app.tools.builtin import time_now
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
