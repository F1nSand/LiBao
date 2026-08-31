"""本地单机化：取消 in-flight 测试（进程内 spawn_run + fut.cancel() 真正中断运行中的图）。"""
from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.orchestration.graph import build_graph
from app.orchestration.stream_core import stream_graph_events
from app.orchestration.task_worker import (
    register_running_task,
    route_cancel,
    running_task,
    spawn_run,
    task_guard,
    unregister_running_task,
)
from app.services.task import TaskService
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, User
from app.storage.repositories.task import TaskRepository


class SlowChatModel:
    """首个 ainvoke 挂起 10s（模拟长 LLM 调用），供取消在挂起点中断。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        await asyncio.sleep(10)
        return AIMessage(content="太慢了不该到这一步")


@pytest.fixture
async def cancel_fixture(monkeypatch, tmp_path):
    store = get_store()
    uid = uuid.uuid4().hex[:8]
    async with store.session() as session:
        await session.flush()
        user = User(username=f"cancel_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="取消测试助手", model="fake", system_prompt="你是助手。",
            tools=[], max_steps=5, status="published",
        )
        session.add(agent)
        await session.commit()
    monkeypatch.setattr("app.orchestration.nodes.agent_execute.LLMService.build_model", lambda *a, **k: SlowChatModel())
    yield user, agent


async def test_cancel_inflight_interrupts_graph(cancel_fixture):
    user, agent = cancel_fixture
    async with get_store().session() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        task_id = task.id

    graph = build_graph()
    fut = spawn_run(graph=graph, task_id=task_id, trace_id="trace-c")
    await asyncio.sleep(0.3)  # 等注册进 _RUNNING 并挂起在慢 LLM 调用中
    assert running_task(str(task_id)) is fut, "任务未注册进 _RUNNING"

    fut.cancel()  # 真正中断运行中的图
    with contextlib.suppress(asyncio.CancelledError):
        await fut

    async with get_store().session() as session:
        t = await TaskRepository(session).get_by_id(task_id)
        assert t.status != "done"  # 图被中止：on_final 未跑，未覆盖为 done
    assert running_task(str(task_id)) is None  # 注册表已清理（_runner finally）


async def test_cancel_after_then_next_task_runs(cancel_fixture):
    """取消一个 in-flight 后，后续任务仍可正常 spawn_run（注册表不残留）。"""
    user, agent = cancel_fixture
    ids = []
    for _ in range(2):
        async with get_store().session() as session:
            t = await TaskService().submit(session, user, agent.id, {"message": "x"})
            ids.append(str(t.id))

    graph = build_graph()
    fut1 = spawn_run(graph=graph, task_id=uuid.UUID(ids[0]), trace_id="t1")
    await asyncio.sleep(0.3)
    fut1.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await fut1

    fut2 = spawn_run(graph=graph, task_id=uuid.UUID(ids[1]), trace_id="t2")
    await asyncio.sleep(0.3)
    assert running_task(ids[1]) is fut2, "取消后第二个任务未正常注册"
    assert running_task(ids[0]) is None, "已取消任务未从注册表清理"
    fut2.cancel()  # 清理，避免挂 10s
    with contextlib.suppress(asyncio.CancelledError):
        await fut2


async def test_chat_stream_producer_is_cancellable_and_skips_final_callback():
    """普通聊天 SSE 的 graph producer 也必须登记到统一取消表，取消后不触发 on_final。"""

    class SlowGraph:
        async def astream(self, initial, config, stream_mode):
            await asyncio.sleep(10)
            if False:  # pragma: no cover - 仅让函数保持 async generator 形态
                yield ("values", {})

    run_id = f"chat-{uuid.uuid4()}"
    final_called = False

    async def on_final(_state):
        nonlocal final_called
        final_called = True
        return {"content": "不应落库"}

    async def consume():
        async for _ in stream_graph_events(
            graph=SlowGraph(),
            initial={},
            graph_config={"configurable": {"thread_id": run_id}},
            emit=lambda event, payload: f"{event}:{payload}",
            on_final=on_final,
            run_id=run_id,
        ):
            pass

    consumer = asyncio.create_task(consume())
    for _ in range(20):
        if running_task(run_id) is not None:
            break
        await asyncio.sleep(0.01)
    assert running_task(run_id) is not None

    await route_cancel(run_id)
    await asyncio.wait_for(consumer, timeout=1)
    assert final_called is False
    assert running_task(run_id) is None


async def test_cancel_intent_survives_registration_race():
    """HTTP cancel 可能先于 chat graph producer 注册，注册后仍必须立即中断。"""
    run_id = f"chat-race-{uuid.uuid4()}"
    await route_cancel(run_id)
    producer = asyncio.create_task(asyncio.sleep(10))
    register_running_task(run_id, producer)
    try:
        await asyncio.wait_for(producer, timeout=1)
    except asyncio.CancelledError:
        pass
    assert producer.cancelled()
    unregister_running_task(run_id, producer)
    assert running_task(run_id) is None


async def test_task_cancel_waits_for_finalization_guard(cancel_fixture):
    """取消与最终落库共用 guard；finalization 持锁时 cancel 不得抢先改终态。"""
    user, agent = cancel_fixture
    async with get_store().session() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        await TaskService().set_running(session, task)
        task_id = str(task.id)

        lock = task_guard(task_id)
        await lock.acquire()
        cancel_job = asyncio.create_task(TaskService().cancel(session, task))
        await asyncio.sleep(0)
        assert not cancel_job.done()
        lock.release()
        await cancel_job
        assert task.status == "cancelled"


async def test_tool_execution_cancellation_interrupts_graph(cancel_fixture, monkeypatch):
    """工具执行挂起时取消，graph 不得继续到最终回复。"""
    from app.tools.builtin import register_builtin_tools
    from app.tools.executor import ToolResult

    register_builtin_tools()

    async def slow_execute(*_args, **_kwargs):
        await asyncio.sleep(10)
        return ToolResult(ok=True, output={}, summary="不应完成", duration_ms=0)

    monkeypatch.setattr("app.tools.executor.execute", slow_execute)
    user, agent = cancel_fixture
    agent.tools = ["tl_time_now"]
    async with get_store().session() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        task_id = task.id

    class ToolCallingModel:
        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            return AIMessage(
                content="",
                tool_calls=[{"name": "time_now", "args": {}, "id": "slow-call", "type": "tool_call"}],
            )

    monkeypatch.setattr(
        "app.orchestration.nodes.agent_execute.LLMService.build_model", lambda *a, **k: ToolCallingModel()
    )
    fut = spawn_run(graph=build_graph(), task_id=task_id, trace_id="trace-tool-cancel")
    await asyncio.sleep(0.5)
    async with get_store().session() as session:
        cancelled_task = await TaskRepository(session).get_by_id(task_id)
        await TaskService().cancel(session, cancelled_task)
    await route_cancel(str(task_id))
    with contextlib.suppress(asyncio.CancelledError):
        await fut

    async with get_store().session() as session:
        cancelled = await TaskRepository(session).get_by_id(task_id)
        assert cancelled.status == "cancelled"
        assert cancelled.output is None
