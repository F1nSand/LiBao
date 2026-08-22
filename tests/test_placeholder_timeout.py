"""M6 前开放项：占位 TTL 看门狗（B1）+ 事件 urgent 档（B3）+ placeholder_events 写端 测试。

覆盖：超时占位 → route 回填 error + 移除；新鲜占位不误杀；urgent 事件置顶优先于 regular；
任务流结束时在途占位写入 task.placeholder_events（docs 04 §3.3 F5）。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage

from app.orchestration.graph import build_graph
from app.orchestration.nodes.route import route_node
from app.orchestration.task_run import run_task_graph
from app.services.events import drain_events, emit_event
from app.services.task import TaskService
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, User
from app.storage.repositories.task import TaskRepository
from app.tools.builtin import register_builtin_tools
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
        pass
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
        pass
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
        pass
        set_dispatch_ctx(None)


async def test_task_writes_placeholder_events():
    """任务流结束：在途占位（initiate_demo）写入 task.placeholder_events（docs 04 §3.3 F5）。"""
    register_builtin_tools()
    uid = uuid.uuid4().hex[:8]
    try:
        async with get_store().session() as session:
            await session.flush()
            user = User(username=f"pl_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
            session.add(user)
            await session.flush()
            agent = AgentConfig(
                org_id=uuid.UUID(int=0), name="占位助手", model="fake", system_prompt="你是助手。",
                tools=["tl_initiate_demo"], max_steps=5, status="published",
            )
            session.add(agent)
            await session.commit()
            task = await TaskService().submit(session, user, agent.id, {"message": "发起占位任务"})
            task_id = task.id

        class FakeModel:
            def __init__(self) -> None:
                self._n = 0

            def bind_tools(self, tools, **kwargs):
                return self

            async def ainvoke(self, messages):
                self._n += 1
                if self._n == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "initiate_demo",
                                "args": {"delay": 0, "note": "x"},
                                "id": "call_p",
                                "type": "tool_call",
                            }
                        ],
                    )
                return AIMessage(content="已发起。")

        graph = build_graph()
        set_dispatch_ctx({"thread_key": str(task_id)})
        try:
            await run_task_graph(
                graph=graph, sessionmaker=None, task_id=task_id,
                trace_id="trace-pl", model_override=FakeModel(),
            )
        finally:
            pass
            set_dispatch_ctx(None)

        async with get_store().session() as session:
            t = await TaskRepository(session).get_by_id(task_id)
            assert t.status == "done"
            assert t.placeholder_events, "占位任务应写入 task.placeholder_events"
            assert t.placeholder_events[0]["job_ref"].startswith("job_")
    finally:
        pass
        