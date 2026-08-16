"""route 节点（docs 01 §3.1/§5.3.1）。轮边界安全点：排空事件收件箱 + 裁决 + 回填占位任务。

M4 完整版最小闭环（docs 01 §5.3.1/§5.3.2）：事件只在轮边界（本节点入口）被消费——
`job_done` 命中在途占位任务 → 经 dispatch ctx 发回填 tool_result（前端占位卡解析）；
其余 regular 事件追加 SystemMessage 备注（模型本轮可见）。urgent/light 预留。
"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState
from app.services.events import arbitrate, drain_events
from app.tools.context import get_dispatch_ctx


def _event_note(event: dict[str, Any]) -> str:
    result = event.get("result")
    if isinstance(result, dict):
        body = str(result.get("note") or result.get("output") or result)
    else:
        body = str(result or "")
    return f"[事件 {event.get('type')}] {body[:300]}"


async def route_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    flags = dict(state.get("flags", {}))
    flags.setdefault("steps", 0)
    flags.setdefault("status", "running")

    thread_key = str((config or {}).get("configurable", {}).get("thread_id", "")) if config else ""
    events = drain_events(thread_key)

    # 匹配占位任务 → 回填 tool_result（前端按 job_ref 更新占位卡）
    placeholder_jobs = list(state.get("placeholder_jobs", []))
    done_refs: set[str] = set()
    for ev in events:
        if ev.get("type") == "job_done" and (job_ref := ev.get("job_ref")):
            match = next((p for p in placeholder_jobs if p["job_ref"] == job_ref), None)
            if match is not None:
                done_refs.add(job_ref)
                push = (get_dispatch_ctx() or {}).get("push")
                if push is not None:
                    push(
                        "tool_result",
                        {
                            "tool_call_id": match["tool_call_id"],
                            "tool_name": match["tool_name"],
                            "ok": True,
                            "summary": "后台任务完成",
                            "structured": ev.get("result"),
                            "placeholder": False,
                            "job_ref": job_ref,
                            "duration_ms": 0,
                        },
                    )
                continue  # 已回填，不再进 context 备注

    # 规则裁决器：regular 事件排空进 context（模型下一轮可见）；job_done 已回填不进备注
    pending = arbitrate([e for e in events if e.get("type") != "job_done"])

    msgs: list[Any] = []
    if pending:
        msgs.append(SystemMessage(content="[后台事件提醒] " + " | ".join(_event_note(e) for e in pending)))

    return {
        "flags": flags,
        "tool_results": [],
        "run_logs": [],
        "messages": msgs,
        "pending_events": [],
        "placeholder_jobs": [p for p in placeholder_jobs if p["job_ref"] not in done_refs],
    }
