"""route 节点（docs 01 §3.1/§5.3.1）。轮边界安全点：排空事件收件箱 + 裁决 + 回填/超时占位任务。

M4 完整版最小闭环（docs 01 §5.3.1/§5.3.2）+ M5/M6 前补强：
- `job_done` 命中在途占位任务 → 经 dispatch ctx 发回填 tool_result（前端占位卡解析）；
- 占位任务超 TTL（看门狗）→ 发超时回填 tool_result（placeholder:false + error）+ 移除；
- urgent 事件置顶进 context（「紧急」优先响应；regular 排后；light 预留）。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from app.orchestration.state_schema import AgentState
from app.services.events import arbitrate, drain_events
from app.tools.context import get_dispatch_ctx

# 占位任务 TTL（docs 01 §5.5 看门狗：超时未回填 → 置失败；轮边界惰性判定，无独立定时器）
PLACEHOLDER_TTL_S = 120


def _event_note(event: dict[str, Any]) -> str:
    result = event.get("result")
    if isinstance(result, dict):
        body = str(result.get("note") or result.get("output") or result)
    else:
        body = str(result or "")
    return f"[事件 {event.get('type')}] {body[:300]}"


def _push_backfill(push: Any, placeholder: dict[str, Any], *, ok: bool, summary: str, structured: Any) -> None:
    """发一条 tool_result 回填帧（占位卡解析：placeholder:false + 同 job_ref）。"""
    if push is None:
        return
    push(
        "tool_result",
        {
            "tool_call_id": placeholder["tool_call_id"],
            "tool_name": placeholder["tool_name"],
            "ok": ok,
            "summary": summary,
            "structured": structured,
            "placeholder": False,
            "job_ref": placeholder["job_ref"],
            "duration_ms": 0,
        },
    )


async def route_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    flags = dict(state.get("flags", {}))
    flags.setdefault("steps", 0)
    flags.setdefault("status", "running")

    thread_key = str((config or {}).get("configurable", {}).get("thread_id", "")) if config else ""
    events = drain_events(thread_key)
    push = (get_dispatch_ctx() or {}).get("push")

    # ① job_done 命中占位任务 → 回填 tool_result
    placeholder_jobs = list(state.get("placeholder_jobs", []))
    done_refs: set[str] = set()
    for ev in events:
        if ev.get("type") == "job_done" and (job_ref := ev.get("job_ref")):
            match = next((p for p in placeholder_jobs if p["job_ref"] == job_ref), None)
            if match is not None:
                done_refs.add(job_ref)
                _push_backfill(push, match, ok=True, summary="后台任务完成", structured=ev.get("result"))

    # ② 占位 TTL 看门狗：超时未回填 → 置失败（docs 01 §5.5，轮边界惰性判定）
    now = time.time()
    for p in placeholder_jobs:
        if p["job_ref"] in done_refs:
            continue
        try:
            created_ts = datetime.fromisoformat(p["created_at"]).timestamp()
        except (ValueError, TypeError):
            created_ts = now  # 无法解析视为新鲜（不误杀）
        if now - created_ts > PLACEHOLDER_TTL_S:
            done_refs.add(p["job_ref"])
            _push_backfill(push, p, ok=False, summary="后台任务超时", structured={"error": "后台任务超时（TTL）"})

    # ③ 事件裁决：urgent 置顶（紧急优先），regular 排后进 context；light 预留
    rest = [e for e in events if e.get("type") != "job_done"]
    classified = arbitrate(rest)
    urgent, regular = classified["urgent"], classified["regular"]

    msgs: list[Any] = []
    if urgent:
        msgs.append(SystemMessage(content="[紧急事件，请优先处理] " + " | ".join(_event_note(e) for e in urgent)))
    if regular:
        msgs.append(SystemMessage(content="[后台事件提醒] " + " | ".join(_event_note(e) for e in regular)))

    return {
        "flags": flags,
        "tool_results": [],
        "run_logs": [],
        "messages": msgs,
        "pending_events": [],
        "placeholder_jobs": [p for p in placeholder_jobs if p["job_ref"] not in done_refs],
    }
