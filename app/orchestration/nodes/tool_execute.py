"""tool_execute 节点（docs 01 §3.1/§7.3）。执行模型发起的工具调用 → ToolMessage + tool_results。

结果 shape 对齐 docs 04 §3.2 message.tool_calls：{tool_call_id, tool_name, position, input, output, ok, duration_ms}。
"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState
from app.tools import executor
from app.tools.registry import get, get_by_name


async def tool_execute_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    last = state["messages"][-1]
    tool_msgs: list[ToolMessage] = []
    results: list[dict[str, Any]] = []

    for position, tc in enumerate(last.tool_calls or []):
        spec = get_by_name(tc["name"]) or get(tc["name"])
        if spec is None:
            content = f"未知工具: {tc['name']}"
            tool_msgs.append(ToolMessage(content=content, tool_call_id=tc["id"]))
            results.append(
                {
                    "tool_call_id": tc["id"],
                    "tool_name": tc["name"],
                    "position": position,
                    "input": tc.get("args", {}),
                    "output": None,
                    "ok": False,
                    "duration_ms": 0,
                }
            )
            continue

        result = await executor.execute(spec, tc.get("args") or {})
        results.append(
            {
                "tool_call_id": tc["id"],
                "tool_name": spec.name,
                "position": position,
                "input": tc.get("args", {}),
                "output": result.output,
                "ok": result.ok,
                "duration_ms": result.duration_ms,
            }
        )
        content = result.summary if result.ok else f"错误: {result.error}"
        tool_msgs.append(ToolMessage(content=content, tool_call_id=tc["id"]))

    return {"messages": tool_msgs, "tool_results": results}
