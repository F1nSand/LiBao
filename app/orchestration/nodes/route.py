"""route 节点（docs 01 §3.1）。M1 恒为单 Agent（single）；多 Agent 模板在 M4 预留。"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState


async def route_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    flags = dict(state.get("flags", {}))
    flags.setdefault("steps", 0)
    flags.setdefault("status", "running")
    return {"flags": flags}
