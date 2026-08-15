"""工具执行上下文（M3）。ContextVar 承载请求级 org 上下文，供 kb_search 等需 DB 的工具使用。

tool_execute_node 在 executor.execute 前 set_tool_org(agent_config.org_id)；
async handler 与节点同 task 直读；asyncio.to_thread 亦拷贝 context。
"""
from __future__ import annotations

from contextvars import ContextVar

TOOL_ORG_ID: ContextVar[str | None] = ContextVar("tool_org_id", default=None)


def set_tool_org(org_id: str | None) -> None:
    TOOL_ORG_ID.set(org_id)


def get_tool_org() -> str | None:
    return TOOL_ORG_ID.get()
