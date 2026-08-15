"""内置工具注册。M1：tl_time_now；M2：tl_demo_notify（人工确认流程演示）；M2.5：tl_tool_search（工具发现元工具）。"""
from __future__ import annotations

from app.tools.builtin import demo_notify, time_now, tool_search
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
            idempotent=False,  # 时间查询不可去重（缓存会返回陈旧时间）
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
    register(
        ToolSpec(
            id="tl_tool_search",
            name="tool_search",
            description=(
                "搜索平台已注册的工具目录，返回匹配工具的名称与路由描述（何时用/何时别用），"
                "不含参数 schema。需要确定某个任务可用什么工具时先搜索再选择。"
                "反例：不要用它执行任务或回答非工具发现问题。"
            ),
            params_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "自然语言搜索关键词"}},
                "required": ["query"],
            },
            tool_type=ToolType.PERCEPTION,
            enabled=True,
            require_confirm=False,
            idempotent=False,
            sandbox=SandboxLevel.NONE,
            timeout_ms=5000,
            handler=tool_search.tool_search_handler,
        )
    )
