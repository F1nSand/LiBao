"""agent_execute 节点（docs 01 §3.1/§4）。bind_tools(ACI) + model.ainvoke 驱动 LLM 决策。

token 级流式不在此 yield：T10 用 graph.astream(stream_mode=["messages"]) 截获模型 chunk。
测试注入：config["configurable"]["model"] 可覆盖模型（mock LLM）。
run_log（type=llm）与 totals（token 累计）在此收集，T10 统一落库。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.core.llm import LLMService
from app.orchestration.context_builder import build_agent_tools, build_context
from app.orchestration.state_schema import AgentState
from app.orchestration.stream_core import message_text


def _resolve_model(state: AgentState, config: Optional[RunnableConfig]) -> Any:  # noqa: UP045  LangGraph 需 Optional 形式
    override = (config or {}).get("configurable", {}).get("model")
    if override is not None:
        return override
    agent = state.get("agent_config", {})
    return LLMService.build_model(agent.get("model"))


def _text_of(response: Any) -> str:
    """提取最终回答文本（兼容 content 为 str 或 content blocks 列表）。"""
    return message_text(getattr(response, "content", ""))


async def agent_execute_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    agent = state.get("agent_config", {})
    trace_id = (config or {}).get("configurable", {}).get("trace_id")

    # M2.5：两段式门控（≤ aci_full_limit 全量；超过 → tool_search + 选中注入）。
    # 每轮强制重算（不读 state.active_tools 缓存）——选中注入依赖本轮 selected_tool_names，
    # 复用旧 active_tools 会让 tool_search 结果永远进不了下一轮 bind_tools（实测坑）。
    active_tools = build_agent_tools(agent.get("tools", []), state.get("selected_tool_names", []))

    model = _resolve_model(state, config).bind_tools(active_tools)

    start = time.perf_counter()
    response = await model.ainvoke(build_context(state))
    duration_ms = int((time.perf_counter() - start) * 1000)

    # token 统计累计（totals 为 LastValue，读旧值再加）
    totals = dict(state.get("totals", {}))
    usage = getattr(response, "usage_metadata", None) or {}
    totals["prompt_tokens"] = totals.get("prompt_tokens", 0) + int(usage.get("input_tokens", 0))
    totals["completion_tokens"] = totals.get("completion_tokens", 0) + int(usage.get("output_tokens", 0))
    totals["total_tokens"] = totals.get("total_tokens", 0) + int(usage.get("total_tokens", 0))

    flags = dict(state.get("flags", {}))
    flags["steps"] = flags.get("steps", 0) + 1

    return {
        "messages": [response],
        "totals": totals,
        "flags": flags,
        "run_logs": (state.get("run_logs") or [])
        + [
            {
                "node": "agent_execute",
                "type": "llm",
                "trace_id": trace_id,
                "input": {"model": agent.get("model"), "tool_count": len(active_tools)},
                "output": {"content": _text_of(response)[:500]},
                "token_usage": usage or None,
                "duration_ms": duration_ms,
                "status": "ok",
            }
        ],
    }
