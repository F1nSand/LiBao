"""M6 前开放项：占位 TTL 看门狗（B1）+ 事件 urgent 档（B3）测试。

覆盖：超时占位 → route 回填 error + 移除；新鲜占位不误杀；urgent 事件置顶优先于 regular。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.orchestration.nodes.route import route_node
from app.services.events import drain_events, emit_event
from app.tools.context import set_dispatch_ctx


def _state(jobs):
    return {"flags": {}, "placeholder_jobs": jobs}


async def test_placeholder_ttl_timeout_backfills_error():
    old_ts = (datetime.now(UTC) - timedelta(seconds=200)).isoformat()
    pushed: list[tuple[str, dict]] = []

    def push(t: str, p: dict) -> str:
        pushed.append((t, p))
        return ""

    set_dispatch_ctx({"thread_key": "thr-ttl", "push": push})
    try:
        out = await route_node(
            _state(
                [{"job_ref": "job_old", "tool_call_id": "call_1", "tool_name": "initiate_demo", "created_at": old_ts}]
            ),
            {"configurable": {"thread_id": "thr-ttl"}},
        )
        backfills = [p for t, p in pushed if t == "tool_result" and p["job_ref"] == "job_old"]
        assert backfills and backfills[0]["placeholder"] is False and backfills[0]["ok"] is False
        assert "超时" in backfills[0]["summary"]
        assert out["placeholder_jobs"] == []  # 超时任务已移除
    finally:
        set_dispatch_ctx(None)


async def test_fresh_placeholder_not_timed_out():
    fresh_ts = datetime.now(UTC).isoformat()
    pushed: list[tuple[str, dict]] = []

    def push(t: str, p: dict) -> str:
        pushed.append((t, p))
        return ""

    set_dispatch_ctx({"thread_key": "thr-fresh", "push": push})
    try:
        out = await route_node(
            _state([{"job_ref": "job_fresh", "tool_call_id": "call_2", "tool_name": "x", "created_at": fresh_ts}]),
            {"configurable": {"thread_id": "thr-fresh"}},
        )
        assert pushed == []  # 新鲜占位不触发超时
        assert len(out["placeholder_jobs"]) == 1  # 保留
    finally:
        set_dispatch_ctx(None)


async def test_urgent_event_top_priority():
    drain_events("thr-u")
    emit_event("thr-u", {"type": "x", "priority": "urgent", "result": {"note": "紧急告警"}})
    emit_event("thr-u", {"type": "y", "priority": "regular", "result": {"note": "普通事件"}})
    set_dispatch_ctx({"thread_key": "thr-u"})
    try:
        out = await route_node(_state([]), {"configurable": {"thread_id": "thr-u"}})
        notes = [m.content for m in out["messages"] if m.type == "system"]
        assert notes, "应有事件备注"
        assert "紧急告警" in notes[0], "urgent 应置顶在第一条"
        assert any("普通事件" in n for n in notes)
        assert "紧急" in notes[0]
    finally:
        set_dispatch_ctx(None)
