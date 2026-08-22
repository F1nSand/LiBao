"""T2 cancel_listener + spawn_run claim 测试（db+redis）：publish_cancel → 持有实例的 in-flight 图被中断。"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from app.core.instance import get_instance_id
from app.storage.redis import (
    close_redis,
    get_redis,
    get_task_owner,
    init_redis,
    publish_cancel,
)
from langchain_core.messages import AIMessage

from app.core.security import hash_password
from app.orchestration.graph import build_graph
from app.orchestration.task_worker import cancel_listener, running_task, spawn_run
from app.services.task import TaskService
from app.storage.db import init_db, set_sessionmaker
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Org, User
from tests.conftest import requires_db, requires_redis

pytestmark = [requires_db, requires_redis]


class SlowChatModel:
    """首个 ainvoke 挂起 10s（模拟长 LLM 调用），供 cancel 在挂起点中断。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        await asyncio.sleep(10)
        return AIMessage(content="太慢了不该到这一步")


@pytest.fixture
async def worker_cancel_fixture(monkeypatch):
    init_redis()
    engine, sessionmaker = init_db()
    set_sessionmaker(sessionmaker)
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-wc-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"wc_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="取消监听助手", model="fake", system_prompt="你是助手。", tools=[], max_steps=5,
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


async def test_spawn_run_claims_and_cancel_listener_interrupts(worker_cancel_fixture):
    sessionmaker, user, agent = worker_cancel_fixture
    async with get_store().session(sessionmaker) as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        task_id = str(task.id)

    graph = build_graph()
    iid = get_instance_id()
    fut = spawn_run(graph=graph, sessionmaker=sessionmaker, task_id=task.id, trace_id="trace-wc")

    # 等 _runner 跑起来：claim 写入 + 图挂起在慢 LLM
    for _ in range(40):
        if await get_task_owner(task_id) == iid and running_task(task_id) is not None:
            break
        await asyncio.sleep(0.05)
    assert await get_task_owner(task_id) == iid  # spawn_run 进入即 claim

    # 启动 cancel_listener，模拟跨实例 cancel 信号
    listener = asyncio.create_task(cancel_listener(iid))
    await asyncio.sleep(0.1)  # 等订阅完成
    await publish_cancel(iid, task_id)

    # 等 cancel 生效：fut 被 cancel → _runner finally 清 claim + 注册表
    for _ in range(40):
        if running_task(task_id) is None:
            break
        await asyncio.sleep(0.05)
    assert running_task(task_id) is None
    assert await get_task_owner(task_id) is None  # claim 已清除
    assert fut.cancelled() or fut.done()

    listener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listener
