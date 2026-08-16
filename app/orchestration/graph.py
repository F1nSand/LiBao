"""主图（docs 01 §3.1，ADR-01）。单主图 + 节点策略；M1 恒走单 Agent（multi 为 M4 接缝）。

流：START→route→memory_inject→agent_execute→(有 tool_calls ?→tool_execute→memory_inject
| 无→context_update)→finalize→END
M3：memory_inject 每轮在 LLM 前注入长期记忆（user_id 缺失/桥未设时静默跳过）。
max_steps 守卫：steps 达上限后 tool_execute 直接转 context_update（死亡螺旋防护 OC10）。
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
from app.orchestration.subgraphs.proposer_reviewer import proposer_node, reviewer_node, summarize_node


def _steps(state: dict[str, Any]) -> int:
    return int(state.get("flags", {}).get("steps", 0))


def _max_steps(state: dict[str, Any]) -> int:
    return int(state.get("agent_config", {}).get("max_steps", 50))


def after_agent(state: dict[str, Any]) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tool_execute"
    return "context_update"


def after_tool(state: dict[str, Any]) -> str:
    if _steps(state) >= _max_steps(state):
        return "context_update"
    return "memory_inject"  # M3：每轮 LLM 前重注入（工具轮转后亦然）


def route_path(state: dict[str, Any]) -> str:
    """单 Agent / 多 Agent（proposer-reviewer）分流（M4）：graph_template 决定。"""
    template = (state.get("agent_config", {}) or {}).get("graph_template", "single")
    return "multi" if template == "proposer_reviewer" else "single"


def build_graph(checkpointer: Any = None) -> Any:
    g = StateGraph(AgentState)
    g.add_node("route", route_node)
    g.add_node("memory_inject", memory_inject_node)
    g.add_node("agent_execute", agent_execute_node)
    g.add_node("tool_execute", tool_execute_node)
    g.add_node("context_update", context_update_node)
    g.add_node("finalize", finalize_node)
    g.add_node("proposer", proposer_node)
    g.add_node("reviewer", reviewer_node)
    g.add_node("summarize", summarize_node)

    g.add_edge(START, "route")
    g.add_conditional_edges("route", route_path, {"single": "memory_inject", "multi": "proposer"})
    g.add_edge("memory_inject", "agent_execute")
    g.add_conditional_edges(
        "agent_execute",
        after_agent,
        {"tool_execute": "tool_execute", "context_update": "context_update"},
    )
    g.add_conditional_edges(
        "tool_execute",
        after_tool,
        {"memory_inject": "memory_inject", "context_update": "context_update"},
    )
    g.add_edge("context_update", "finalize")
    # 多 Agent（proposer-reviewer）路径：proposer → reviewer → summarize → finalize
    g.add_edge("proposer", "reviewer")
    g.add_edge("reviewer", "summarize")
    g.add_edge("summarize", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)
