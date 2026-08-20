"""工具执行上下文（M3/M4）。ContextVar 承载请求级 org 上下文与 subagent 派发事件汇。

tool_execute_node 在 executor.execute 前 set_tool_org(agent_config.org_id)；
async handler 与节点同 task 直读；asyncio.to_thread 亦拷贝 context。
dispatch ctx 由 stream_graph_events 在 producer 启动前设置：tl_dispatch_subagent handler
读它发 agent_switch 事件（chat 路径 emit=sse_emitter，task 路径 emit=薄转发）。
"""
from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

TOOL_ORG_ID: ContextVar[str | None] = ContextVar("tool_org_id", default=None)
TOOL_WORKSPACE_ROOT: ContextVar[str | None] = ContextVar("tool_workspace_root", default=None)


def set_tool_org(org_id: str | None) -> None:
    TOOL_ORG_ID.set(org_id)


def get_tool_org() -> str | None:
    return TOOL_ORG_ID.get()


def set_tool_workspace_root(root: str | None) -> None:
    TOOL_WORKSPACE_ROOT.set(root)


def get_tool_workspace_root() -> str | None:
    return TOOL_WORKSPACE_ROOT.get()


# subagent 派发上下文：{emit, model_builder?, main_name}。emit 发 agent_switch；
# model_builder 供测试注入假模型；main_name 为事件里的主 agent 名（默认「通用助手」）。
DispatchCtx = dict[str, Any]
_DISPATCH_CTX: ContextVar[DispatchCtx | None] = ContextVar("dispatch_ctx", default=None)


def set_dispatch_ctx(ctx: DispatchCtx | None) -> None:
    _DISPATCH_CTX.set(ctx)


def get_dispatch_ctx() -> DispatchCtx | None:
    return _DISPATCH_CTX.get()


def dispatch_emit() -> Callable[[str, dict[str, Any]], str] | None:
    """读当前派发事件汇（无 → None，handler 静默跳过事件发射）。"""
    ctx = _DISPATCH_CTX.get()
    return ctx.get("emit") if ctx else None


def dispatch_thread_key() -> str:
    """读当前线程 key（后台任务回填事件投递目标；无 → ""）。"""
    ctx = _DISPATCH_CTX.get()
    return str(ctx.get("thread_key", "")) if ctx else ""

