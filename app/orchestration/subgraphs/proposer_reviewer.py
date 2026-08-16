"""proposer-reviewer 二段协作（docs 01 §3.5 / docs 07 M4）。

上下文隔离：proposer 只收任务原文；reviewer 只收草案；summarize 收草案+评审 → 定稿。
协作节点各自产出 agent_switch（stream_core 转 SSE 事件，前端渲染切换标记）。
MVP：不 bind_tools / 不子图内 interrupt（随主图 checkpoint，interrupt 为 M4 完整版）。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState
from app.orchestration.stream_core import message_text

_PROPOSER_PROMPT = "你是方案提案者。针对任务输出完整、可执行的方案/回答。只输出方案本身。"
_REVIEWER_PROMPT = "你是方案评审者。审查下面的方案，指出问题、漏洞或改进点并给修订建议。只输出评审意见。"
_SUMMARIZE_PROMPT = "你是汇总者。综合方案与评审意见，输出最终定稿的回答。只输出最终回答。"


def _resolve_model(state: AgentState, config: RunnableConfig | None) -> Any:
    override = (config or {}).get("configurable", {}).get("model")
    if override is not None:
        return override
    from app.core.llm import LLMService

    return LLMService.build_model(state.get("agent_config", {}).get("model"))


async def _llm_pass(
    state: AgentState, config: RunnableConfig | None, node: str, sys_prompt: str, human_content: str
) -> tuple[str, list[dict[str, Any]]]:
    model = _resolve_model(state, config)
    start = time.perf_counter()
    resp = await model.ainvoke([SystemMessage(content=sys_prompt), HumanMessage(content=human_content)])
    duration_ms = int((time.perf_counter() - start) * 1000)
    text = message_text(getattr(resp, "content", ""))
    run_logs = (state.get("run_logs") or []) + [
        {
            "node": node,
            "type": "llm",
            "trace_id": (config or {}).get("configurable", {}).get("trace_id"),
            "input": {"model": state.get("agent_config", {}).get("model")},
            "output": {"content": text[:500]},
            "duration_ms": duration_ms,
            "status": "ok",
        }
    ]
    return text, run_logs


async def proposer_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    """提案：只收任务原文（隔离，不传全历史）。"""
    task = state["messages"][-1].content
    text, run_logs = await _llm_pass(state, config, "proposer", _PROPOSER_PROMPT, task)
    return {
        "drafts": {"proposal": text},
        "agent_switch": {"from_agent": "assistant", "to_agent": "proposer", "reason": "开始方案提案"},
        "run_logs": run_logs,
    }


async def reviewer_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    """评审：只收草案。"""
    drafts = state.get("drafts", {}) or {}
    text, run_logs = await _llm_pass(
        state, config, "reviewer", _REVIEWER_PROMPT, f"方案：\n{drafts.get('proposal', '')}"
    )
    return {
        "drafts": {**drafts, "review": text},
        "agent_switch": {"from_agent": "proposer", "to_agent": "reviewer", "reason": "评审方案"},
        "run_logs": run_logs,
    }


async def summarize_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    """汇总：草案+评审 → 定稿（append 最终 assistant 消息，finalize 组装）。"""
    drafts = state.get("drafts", {}) or {}
    body = f"方案：\n{drafts.get('proposal', '')}\n\n评审：\n{drafts.get('review', '')}"
    text, run_logs = await _llm_pass(state, config, "summarize", _SUMMARIZE_PROMPT, body)
    return {
        "messages": [AIMessage(content=text)],
        "agent_switch": {"from_agent": "reviewer", "to_agent": "assistant", "reason": "汇总定稿"},
        "run_logs": run_logs,
    }
