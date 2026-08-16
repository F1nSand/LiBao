"""2f system-logs 测试（DB-backed）：分页/过滤/序列化 level 映射/trace 时间线。"""
from __future__ import annotations

import uuid

import pytest

from app.api.routers.system import _trace_event
from app.services.serializers import serialize_run_log
from app.storage.db import init_db
from app.storage.repositories.run_log import RunLogRepository
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def log_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        repo = RunLogRepository(session)
        await repo.create(
            trace_id=f"tr_{uid}", node="agent_execute", type="llm", status="ok",
            input={"model": "deepseek-x"}, output={"content": "你好"}, duration_ms=10,
            token_usage={"total_tokens": 5},
        )
        await repo.create(
            trace_id=f"tr_{uid}", node="tool_execute", type="tool", status="error",
            input={"x": 1}, output={"error": "boom"}, duration_ms=3,
        )
        await repo.create(trace_id=f"other_{uid}", node="agent_execute", type="llm", status="retried", output={})
        await session.commit()
    yield sessionmaker, uid
    await engine.dispose()


async def test_list_paged_and_filters(log_fixture):
    sessionmaker, uid = log_fixture
    async with sessionmaker() as session:
        repo = RunLogRepository(session)
        items, total = await repo.list_paged(limit=20, offset=0)
        assert total == 3
        items2, total2 = await repo.list_paged(limit=20, offset=0, trace_id=f"tr_{uid}")
        assert total2 == 2
        items3, total3 = await repo.list_paged(limit=20, offset=0, status="error")
        assert total3 == 1
        assert items3[0].node == "tool_execute"


async def test_serialize_run_log_maps_level(log_fixture):
    sessionmaker, uid = log_fixture
    async with sessionmaker() as session:
        repo = RunLogRepository(session)
        items, _ = await repo.list_paged(limit=20, offset=0)
        by_status = {lg.status: lg for lg in items}
        assert serialize_run_log(by_status["ok"])["level"] == "INFO"
        assert serialize_run_log(by_status["error"])["level"] == "ERROR"
        assert serialize_run_log(by_status["retried"])["level"] == "WARNING"
        assert serialize_run_log(by_status["ok"])["service"] == "agent-backend"
        assert serialize_run_log(by_status["ok"])["message"] == "你好"


async def test_trace_events(log_fixture):
    sessionmaker, uid = log_fixture
    async with sessionmaker() as session:
        repo = RunLogRepository(session)
        logs = await repo.list_by_trace_id(f"tr_{uid}")
        events = [_trace_event(lg) for lg in logs]
        assert sorted(e["node_type"] for e in events) == ["llm", "tool"]
        assert sorted(e["status"] for e in events) == ["failed", "success"]
        assert all(e["ts"] > 0 for e in events)
