"""M4 完整版：取消 in-flight 测试（db+redis）。fut.cancel() 真正中断运行中的图，worker 存活、注册表清理。"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.core.security import hash_password
from app.orchestration.graph import build_graph
from app.orchestration.task_worker import process_one, running_task, task_worker
from app.services.task import TaskService
from app.services.task_queue import TaskQueueService
from app.storage.db import init_db, set_sessionmaker
from app.storage.models import AgentConfig, Org, User
from app.storage.redis import close_redis, get_redis, init_redis
from app.storage.repositories.task import TaskRepository
from tests.conftest import requires_db, requires_redis

pytestmark = [requires_db, requires_redis]


class SlowChatModel:
    """首个 ainvoke 挂起 10s（模拟长 LLM 调用），供取消在挂起点中断。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        await asyncio.sleep(10)
        return AIMessage(content="太慢了不该到这一步")


@pytest.fixture
async def cancel_fixture(monkeypatch):
    init_redis()
    engine, sessionmaker = init_db()
    set_sessionmaker(sessionmaker)
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-cancel-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"cancel_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
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
    r = get_redis()
    if r is not None:
        await r.delete("task:queue")
    set_sessionmaker(None)
    await close_redis()
    await engine.dispose()


async def test_cancel_inflight_interrupts_graph(cancel_fixture):
    sessionmaker, user, agent = cancel_fixture
    async with sessionmaker() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        task_id = task.id
    assert await TaskQueueService().enqueue_submit(task_id, "trace-c") is True

    graph = build_graph()
    worker = asyncio.create_task(process_one(graph, sessionmaker))

    # 等 worker 消费并注册进 _RUNNING（挂起在慢 LLM 调用中）
    fut = None
    for _ in range(40):
        fut = running_task(str(task_id))
        if fut is not None:
            break
        await asyncio.sleep(0.05)
    assert fut is not None, "任务未注册进 _RUNNING（worker 未消费？）"

    fut.cancel()  # 真正中断运行中的图
    processed = await worker  # process_one 捕获 CancelledError，worker 正常返回
    assert processed is True

    async with sessionmaker() as session:
        t = await TaskRepository(session).get_by_id(task_id)
        assert t.status != "done"  # 图被中止：on_final 未跑，未覆盖为 done
    assert running_task(str(task_id)) is None  # 注册表已清理（_runner finally）


async def test_worker_survives_cancel_and_processes_next(cancel_fixture):
    """取消一个 in-flight 后，worker 循环仍能消费下一个任务（不因 CancelledError 退出）。"""
    sessionmaker, user, agent = cancel_fixture
    ids = []
    for msg in ("first", "second"):
        async with sessionmaker() as session:
            t = await TaskService().submit(session, user, agent.id, {"message": msg})
            ids.append(str(t.id))
        assert await TaskQueueService().enqueue_submit(t.id, "trace-c") is True

    async def _wait_any_registered() -> str | None:
        """等任意任务注册（BRPOP 从右端取，谁先消费不定）。"""
        for _ in range(40):
            for tid in ids:
                if running_task(tid) is not None:
                    return tid
            await asyncio.sleep(0.05)
        return None

    graph = build_graph()
    stop = asyncio.Event()
    worker = asyncio.create_task(task_worker(graph, sessionmaker, stop))

    first = await _wait_any_registered()
    assert first is not None, "worker 未消费第一个任务"
    running_task(first).cancel()  # 真正中断第一个 in-flight

    # 取消后 worker 循环继续，消费并注册第二个（串行 worker 此时空闲）
    second = None
    for _ in range(40):
        second = next((tid for tid in ids if tid != first and running_task(tid) is not None), None)
        if second is not None:
            break
        await asyncio.sleep(0.05)
    assert second is not None, "取消第一个后 worker 未继续消费第二个"
    running_task(second).cancel()  # 清理，避免挂 10s

    stop.set()
    await worker
    assert running_task(ids[0]) is None and running_task(ids[1]) is None  # 注册表全清理
