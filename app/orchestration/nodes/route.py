"""route 节点（docs 01 §3.1）。M1 恒为单 Agent（single）；多 Agent 模板在 M4 预留。"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState


async def route_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    flags = dict(state.get("flags", {}))
    flags.setdefault("steps", 0)
    flags.setdefault("status", "running")
    # 轮次边界：重置 LastValue 轮次通道（跨轮 checkpoint 不残留上轮 tool_results/run_logs）
    return {"flags": flags, "tool_results": [], "run_logs": []}
