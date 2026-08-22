"""B1 任务队列测试（db+redis）：入队 → worker 消费 → submit done / resume 拒绝 cancelled。"""
from __future__ import annotations

import uuid

import pytest
from app.services.task_queue import TaskQueueService
from app.storage.redis import close_redis, get_redis, get_task_owner, init_redis
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.core.security import hash_password
from app.orchestration.graph import build_graph
from app.orchestration.task_worker import process_one
from app.services.task import TaskService
from app.storage.db import init_db, set_sessionmaker
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Org, RunLog, User
from app.storage.repositories.task import TaskRepository
from tests.conftest import requires_db, requires_redis

pytestmark = [requires_db, requires_redis]


class FakeChatModel:
    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="后台任务完成。")


@pytest.fixture
async def queue_fixture(monkeypatch):
    init_redis()
    engine, sessionmaker = init_db()
    set_sessionmaker(sessionmaker)
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-q-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"q_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="队列助手", model="fake", system_prompt="你是助手。", tools=[], max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.commit()
    monkeypatch.setattr("app.orchestration.nodes.agent_execute.LLMService.build_model", lambda *a, **k: FakeChatModel())
    yield sessionmaker, user, agent
    r = get_redis()
    if r is not None:
        await r.delete("task:queue")
    set_sessionmaker(None)
    await close_redis()
    await engine.dispose()


async def test_enqueue_submit_worker_runs_to_done(queue_fixture):
    sessionmaker, user, agent = queue_fixture
    async with get_store().session(sessionmaker) as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        task_id = task.id
    assert await TaskQueueService().enqueue_submit(task_id, "trace-q") is True
    graph = build_graph()
    processed = await process_one(graph, sessionmaker)
    assert processed is True
    async with get_store().session(sessionmaker) as session:
        t = await TaskRepository(session).get_by_id(task_id)
        assert t.status == "done"
        logs = (await session.execute(select(RunLog).where(RunLog.task_id == task_id))).scalars().all()
        assert len(logs) >= 1  # run_log 带 task_id 落库
    assert await get_task_owner(str(task_id)) is None  # M6-3：done 后 claim 清除


async def test_enqueue_resume_denied_cancels(queue_fixture):
    sessionmaker, user, agent = queue_fixture
    async with get_store().session(sessionmaker) as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        task_id = task.id
        task.status = "waiting_confirm"
        task.pending_confirm = {"thread_id": str(task.id)}
        await session.commit()
    assert await TaskQueueService().enqueue_resume(task_id, approved=False, trace_id="trace-r") is True
    graph = build_graph()
    processed = await process_one(graph, sessionmaker)
    assert processed is True
    async with get_store().session(sessionmaker) as session:
        t = await TaskRepository(session).get_by_id(task_id)
        assert t.status == "cancelled"
