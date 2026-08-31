"""主图（《02》后端设计 §3.1，ADR-01）。单主图 + 节点策略；单通用 Agent，subagent 由主 Agent 经
tl_dispatch_subagent 派发（嵌套 LLM 循环，主图拓扑不变，《02》后端设计 §3.5）。

流：START→route→memory_inject→agent_execute→(有 tool_calls ?→tool_execute→memory_inject
| 无→context_update)→finalize→END
M3：memory_inject 每轮在 LLM 前注入长期记忆（user_id 缺失/桥未设时静默跳过）。
max_steps 守卫（2026-08-24 改进）：steps 达上限后 tool_execute 转「收口轮」agent_execute
（消息通道提示直接作答，防「最后答复 = 工具结果 JSON」裸收尾）；收口轮工具调用被丢弃，
finalize 兜底（回退最近 AI 文本/占位 + max_steps_exceeded flag）。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.orchestration.nodes import (
    agent_execute_node,
    context_update_node,
    finalize_node,
    memory_inject_node,
    route_node,
    tool_execute_node,
)
from app.orchestration.state_schema import AgentState


def _steps(state: dict[str, Any]) -> int:
    return int(state.get("flags", {}).get("steps", 0))


def _max_steps(state: dict[str, Any]) -> int:
    return int(state.get("agent_config", {}).get("max_steps", 50))


def after_agent(state: dict[str, Any]) -> str:
    """agent_execute 后：有工具调用且未超步数 → tool_execute；否则（含收口轮）→ context_update。

    2026-08-24：steps > max_steps 时禁止再开工具轮（收口轮的工具调用被丢弃，finalize 兜底），防死循环。
    """
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None) and _steps(state) <= _max_steps(state):
        return "tool_execute"
    return "context_update"


def after_tool(state: dict[str, Any]) -> str:
    """tool_execute 后：步数到顶 → 收口轮（agent_execute 提示 LLM 直接作答），否则回 LLM 轮。"""
    if _steps(state) >= _max_steps(state):
        return "agent_execute"
    return "memory_inject"  # M3：每轮 LLM 前重注入（工具轮转后亦然）


def build_graph(checkpointer: Any = None) -> Any:
    g = StateGraph(AgentState)
    g.add_node("route", route_node)
    g.add_node("memory_inject", memory_inject_node)
    g.add_node("agent_execute", agent_execute_node)
    g.add_node("tool_execute", tool_execute_node)
    g.add_node("context_update", context_update_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "route")
    g.add_edge("route", "memory_inject")
    g.add_edge("memory_inject", "agent_execute")
    g.add_conditional_edges(
        "agent_execute",
        after_agent,
        {"tool_execute": "tool_execute", "context_update": "context_update"},
    )
    g.add_conditional_edges(
        "tool_execute",
        after_tool,
        {"memory_inject": "memory_inject", "context_update": "context_update", "agent_execute": "agent_execute"},
    )
    g.add_edge("context_update", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)
