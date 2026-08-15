"""T7 任务服务/运行器测试（DB-backed）：submit→run→done、cancel 40902、resume 前置校验、events 回放。

需要 Docker db；DB 不可达自动跳过。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from app.api.routers.tasks import _task_event_stream
from app.core.errors import AppError
from app.core.security import hash_password
from app.orchestration.graph import build_graph
from app.orchestration.task_run import run_task_graph
from app.services.task import TaskService
from app.storage.db import init_db
from app.storage.models import AgentConfig, Org, RunLog, User
from app.storage.repositories.task import TaskRepository
from tests.conftest import requires_db

pytestmark = requires_db


class FakeChatModel:
    def __init__(self) -> None:
        self._n = 0

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        if self._n == 0:
            self._n = 1
            return AIMessage(
                content="", tool_calls=[{"name": "time_now", "args": {}, "id": "call_1", "type": "tool_call"}]
            )
        return AIMessage(content="任务执行完成。")


@pytest.fixture
async def tasks_fixture():
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-tasks-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"tasks_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id,
            name="任务测试助手",
            model="fake",
            system_prompt="你是测试助手。",
            tools=["tl_time_now"],
            max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.commit()
    yield sessionmaker, user, agent
    await engine.dispose()


async def test_submit_and_run_to_done(tasks_fixture):
    sessionmaker, user, agent = tasks_fixture
    graph = build_graph()
    async with sessionmaker() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "现在几点？"})
        task_id = task.id
        assert task.status == "pending"

    await run_task_graph(
        graph=graph, sessionmaker=sessionmaker, task_id=task_id, trace_id="trace-t", model_override=FakeChatModel()
    )

    async with sessionmaker() as session:
        task2 = await TaskRepository(session).get_by_id(task_id)
        assert task2.status == "done"
        assert task2.output and task2.output.get("content") == "任务执行完成。"
        stmt = select(func.count()).select_from(RunLog).where(RunLog.task_id == task_id)
        n = (await session.execute(stmt)).scalar_one()
        assert n > 0  # run_logs 带 task_id


async def test_cancel_done_returns_40902(tasks_fixture):
    sessionmaker, user, agent = tasks_fixture
    async with sessionmaker() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        await TaskService().set_done(session, task, {"content": "ok"})
        with pytest.raises(AppError) as exc:
            await TaskService().cancel(session, task)
        assert exc.value.code == 40902


async def test_resume_precheck_rejects_cancelled(tasks_fixture):
    sessionmaker, user, agent = tasks_fixture
    async with sessionmaker() as session:
        task = await TaskService().create_waiting_confirm(
            session,
            user=user,
            agent_id=agent.id,
            input={},
            value={"node_id": "tool_execute"},
            thread_id=str(uuid.uuid4()),
        )
        await TaskService().set_cancelled(session, task)
        with pytest.raises(AppError) as exc:
            await TaskService().resume_precheck(session, task)
        assert exc.value.code == 40902


async def test_resume_precheck_rejects_expired_ttl(tasks_fixture):
    sessionmaker, user, agent = tasks_fixture
    async with sessionmaker() as session:
        task = await TaskService().create_waiting_confirm(
            session,
            user=user,
            agent_id=agent.id,
            input={},
            value={"node_id": "tool_execute"},
            thread_id=str(uuid.uuid4()),
        )
        # 手工把 created_at 改成 25h 前（超 TTL 24h）
        task.pending_confirm["created_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        session.add(task)
        await session.commit()
        with pytest.raises(AppError) as exc:
            await TaskService().resume_precheck(session, task)
        assert exc.value.code == 40902


async def test_events_replay_done(tasks_fixture):
    sessionmaker, user, agent = tasks_fixture
    async with sessionmaker() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        await TaskService().set_done(session, task, {"content": "完成", "token_usage": {"total_tokens": 10}})
        frames = []
        async for frame in _task_event_stream(session, task):
            frames.append(frame)
        assert frames, "至少回放一帧"
        data = frames[0].split("\n\n")[0].split("data: ", 1)[1]
        import json

        event = json.loads(data)
        assert event["type"] == "done"
        assert event["payload"]["message"]["content"] == "完成"
