"""finalize 节点（docs 01 §3.1/§5.4）。轻量 verifier + 组装最终消息 dict（对齐 message 持久化 / done 事件）。

final_message shape：{role, content, tool_calls[], token_usage, trace_id?}；tool_calls 来自 tool_results（独立核对）。
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState
from app.orchestration.stream_core import message_text


def _assemble_tool_calls(state: AgentState) -> list[dict[str, Any]]:
    results = state.get("tool_results", [])
    out: list[dict[str, Any]] = []
    for r in sorted(results, key=lambda x: x.get("position", 0)):
        out.append(
            {
                "tool_call_id": r.get("tool_call_id"),
                "tool_name": r.get("tool_name"),
                "position": r.get("position", 0),
                "input": r.get("input"),
                "output": r.get("output"),
                "ok": r.get("ok", False),
                # FrontEnd ToolCallRecord 读 status；透传 cancelled（用户拒绝分支）
                "status": r.get("status") or ("done" if r.get("ok", False) else "error"),
                "duration_ms": r.get("duration_ms", 0),
            }
        )
    return out


async def finalize_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    last = state["messages"][-1]
    flags = dict(state.get("flags", {}))
    totals = dict(state.get("totals", {}))

    # 轻量 verifier：模型声称调了工具但无结果 → 记 warning（M1 只记录，不阻断）
    claimed = bool(getattr(last, "tool_calls", None))
    if claimed and not state.get("tool_results"):
        flags["verifier_warning"] = "模型声称调用工具但无对应执行结果"

    # 收口兜底（2026-08-24）：步数守卫强制退出时末条可能是 ToolMessage（工具结果）——
    # 不能当最终答复。回退最近有文本的 AIMessage；全无 → 占位 + max_steps_exceeded flag。
    ai_texts = [
        message_text(m.content)
        for m in reversed(state.get("messages", []))
        if getattr(m, "type", "") == "ai"
    ]
    content = next((t for t in ai_texts if t.strip()), "")
    if not content:
        content = "（已达步数上限，未生成最终答复）"
        flags["max_steps_exceeded"] = True

    flags["status"] = "done"
    totals["steps"] = flags.get("steps", 0)

    final_message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "tool_calls": _assemble_tool_calls(state),
        "token_usage": totals,
    }
    return {"final_message": final_message, "flags": flags, "totals": totals}
