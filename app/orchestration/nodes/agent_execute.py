"""agent_execute 节点（docs 01 §3.1/§4）。bind_tools(ACI) + model.ainvoke 驱动 LLM 决策。

token 级流式不在此 yield：T10 用 graph.astream(stream_mode=["messages"]) 截获模型 chunk。
测试注入：config["configurable"]["model"] 可覆盖模型（mock LLM）。
"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.core.llm import LLMService
from app.orchestration.context_builder import acis_for_tools, build_context
from app.orchestration.state_schema import AgentState


def _resolve_model(state: AgentState, config: Optional[RunnableConfig]) -> Any:  # noqa: UP045  LangGraph 需 Optional 形式
    override = (config or {}).get("configurable", {}).get("model")
    if override is not None:
        return override
    agent = state.get("agent_config", {})
    return LLMService.build_model(agent.get("model"))


async def agent_execute_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    agent = state.get("agent_config", {})

    active_tools = state.get("active_tools")
    if not active_tools:
        active_tools = acis_for_tools(agent.get("tools", []))
    if not active_tools:
        active_tools = state.get("active_tools", [])

    model = _resolve_model(state, config)
    model = model.bind_tools(active_tools)

    response = await model.ainvoke(build_context(state))

    flags = dict(state.get("flags", {}))
    flags["steps"] = flags.get("steps", 0) + 1
    return {"messages": [response], "active_tools": active_tools, "flags": flags}
