"""context_update 节点（《02》后端设计 §3.1/§4.3）。维护代码态状态栏与阶段标记。

状态栏只由受信代码生成（OA2 防投毒）；M1 简单概括 steps/工具调用数。
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState


async def context_update_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    flags = dict(state.get("flags", {}))
    flags["status"] = "finalizing"
    flags["status_bar"] = (
        f"[系统状态] 已执行 {flags.get('steps', 0)} 步，工具调用 {len(state.get('tool_results', []))} 次。"
    )
    return {"flags": flags}
