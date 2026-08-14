"""tool_execute 节点（docs 01 §3.1/§7.3）。执行模型发起的工具调用 → ToolMessage + tool_results。

结果 shape 对齐 docs 04 §3.2 message.tool_calls：{tool_call_id, tool_name, position, input, output, ok, duration_ms}。
"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState
from app.tools import executor
from app.tools.registry import agent_can_use, get, get_by_name


async def tool_execute_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    last = state["messages"][-1]
    trace_id = (config or {}).get("configurable", {}).get("trace_id")
    tool_msgs: list[ToolMessage] = []
    results: list[dict[str, Any]] = []
    run_logs: list[dict[str, Any]] = []

    # 授权谓词与 acis_for_tools 共用 agent_can_use（单一不变量）
    agent_tool_ids = set(state.get("agent_config", {}).get("tools", []) or [])
    for position, tc in enumerate(last.tool_calls or []):
        spec = get_by_name(tc["name"]) or get(tc["name"])
        # 授权校验：只执行 agent 启用集内且 enabled 的工具（防模型幻觉/上下文投毒调用越权工具）
        if not agent_can_use(spec, agent_tool_ids):
            content = f"未知或未启用工具: {tc['name']}"
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
                "summary": result.summary,
                "duration_ms": result.duration_ms,
            }
        )
        content = result.summary if result.ok else f"错误: {result.error}"
        tool_msgs.append(ToolMessage(content=content, tool_call_id=tc["id"]))
        run_logs.append(
            {
                "node": "tool_execute",
                "type": "tool",
                "trace_id": trace_id,
                "input": tc.get("args", {}),
                "output": {"summary": result.summary[:500], "ok": result.ok, "error": result.error},
                "duration_ms": result.duration_ms,
                "status": "ok" if result.ok else "error",
            }
        )

    return {
        "messages": tool_msgs,
        "tool_results": results,
        "run_logs": (state.get("run_logs") or []) + run_logs,
    }
