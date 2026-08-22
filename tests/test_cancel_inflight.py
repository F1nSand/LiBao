"""本地单机化：取消 in-flight 测试（进程内 spawn_run + fut.cancel() 真正中断运行中的图）。"""
from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.orchestration.graph import build_graph
from app.orchestration.task_worker import running_task, spawn_run
from app.services.task import TaskService
from app.storage.db import init_db, set_sessionmaker
from app.storage.file.store import get_store, set_store
from app.storage.models import AgentConfig, Org, User
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
    engine, sessionmaker = init_db()
    set_sessionmaker(sessionmaker)
    store = get_store()
    store.sql_sessionmaker = sessionmaker  # 注入 SQL 兜底（双轨）
    uid = uuid.uuid4().hex[:8]
    async with store.session(sessionmaker) as session:
        org = Org(name=f"测试组织-cancel-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"cancel_{uid}", password_hash="hashed", name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="取消测试助手", model="fake", system_prompt="你是助手。", tools=[], max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.commit()
    monkeypatch.setattr("app.orchestration.nodes.agent_execute.LLMService.build_model", lambda *a, **k: SlowChatModel())
    yield sessionmaker, user, agent
    set_store(None)
    set_sessionmaker(None)
    await engine.dispose()


async def test_cancel_inflight_interrupts_graph(cancel_fixture):
    sessionmaker, user, agent = cancel_fixture
    async with get_store().session(sessionmaker) as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        task_id = task.id

    graph = build_graph()
    fut = spawn_run(graph=graph, sessionmaker=sessionmaker, task_id=task_id, trace_id="trace-c")
    await asyncio.sleep(0.3)  # 等注册进 _RUNNING 并挂起在慢 LLM 调用中
    assert running_task(str(task_id)) is fut, "任务未注册进 _RUNNING"

    fut.cancel()  # 真正中断运行中的图
    with contextlib.suppress(asyncio.CancelledError):
        await fut

    async with get_store().session(sessionmaker) as session:
        t = await TaskRepository(session).get_by_id(task_id)
        assert t.status != "done"  # 图被中止：on_final 未跑，未覆盖为 done
    assert running_task(str(task_id)) is None  # 注册表已清理（_runner finally）


async def test_cancel_after_then_next_task_runs(cancel_fixture):
    """取消一个 in-flight 后，后续任务仍可正常 spawn_run（注册表不残留）。"""
    sessionmaker, user, agent = cancel_fixture
    ids = []
    for _ in range(2):
        async with get_store().session(sessionmaker) as session:
            t = await TaskService().submit(session, user, agent.id, {"message": "x"})
            ids.append(str(t.id))

    graph = build_graph()
    fut1 = spawn_run(graph=graph, sessionmaker=sessionmaker, task_id=uuid.UUID(ids[0]), trace_id="t1")
    await asyncio.sleep(0.3)
    fut1.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await fut1

    fut2 = spawn_run(graph=graph, sessionmaker=sessionmaker, task_id=uuid.UUID(ids[1]), trace_id="t2")
    await asyncio.sleep(0.3)
    assert running_task(ids[1]) is fut2, "取消后第二个任务未正常注册"
    assert running_task(ids[0]) is None, "已取消任务未从注册表清理"
    fut2.cancel()  # 清理，避免挂 10s
    with contextlib.suppress(asyncio.CancelledError):
        await fut2
