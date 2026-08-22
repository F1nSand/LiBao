"""2f system-logs 测试（DB-backed）：分页/过滤/序列化 level 映射/trace 时间线。"""
from __future__ import annotations

import uuid

import pytest

from app.services.serializers import serialize_run_log, serialize_trace_event
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.repositories.run_log import RunLogRepository
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def log_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
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
    async with get_store().session(sessionmaker) as session:
        repo = RunLogRepository(session)
        _, total = await repo.list_paged(limit=20, offset=0)
        assert total >= 3  # 共享 DB：其他测试残留 run_logs，只断言下限
        items2, total2 = await repo.list_paged(limit=20, offset=0, trace_id=f"tr_{uid}")
        assert total2 == 2
        items3, total3 = await repo.list_paged(limit=20, offset=0, trace_id=f"tr_{uid}", status="error")
        assert total3 == 1
        assert items3[0].node == "tool_execute"


async def test_serialize_run_log_maps_level(log_fixture):
    sessionmaker, uid = log_fixture
    async with get_store().session(sessionmaker) as session:
        repo = RunLogRepository(session)
        tr_logs, _ = await repo.list_paged(limit=20, offset=0, trace_id=f"tr_{uid}")
        other_logs, _ = await repo.list_paged(limit=20, offset=0, trace_id=f"other_{uid}")
        by_status = {lg.status: lg for lg in tr_logs + other_logs}
        assert serialize_run_log(by_status["ok"])["level"] == "INFO"
        assert serialize_run_log(by_status["error"])["level"] == "ERROR"
        assert serialize_run_log(by_status["retried"])["level"] == "WARNING"
        assert serialize_run_log(by_status["ok"])["service"] == "agent-backend"
        assert serialize_run_log(by_status["ok"])["message"] == "你好"


async def test_trace_events(log_fixture):
    sessionmaker, uid = log_fixture
    async with get_store().session(sessionmaker) as session:
        repo = RunLogRepository(session)
        logs = await repo.list_by_trace_id(f"tr_{uid}")
        events = [serialize_trace_event(lg) for lg in logs]
        assert sorted(e["node_type"] for e in events) == ["llm", "tool"]
        assert sorted(e["status"] for e in events) == ["failed", "success"]
        assert all(e["ts"] > 0 for e in events)


async def test_aggregate_llm_groups_by_day_model(log_fixture):
    """M6-1 回归：token_usage.cost 需进聚合（旧 SQL 违反 GROUP BY → /system/cost 50001）。"""
    sessionmaker, uid = log_fixture
    async with get_store().session(sessionmaker) as session:
        repo = RunLogRepository(session)
        for cost in (0.5, 0.3):  # 同 model 两行，cost 应求和
            await repo.create(
                trace_id=f"agg_{uid}", node="agent_execute", type="llm", status="ok",
                input={"model": "deepseek-agg"}, output={}, duration_ms=1,
                token_usage={"cost": cost},
            )
        await session.commit()
    async with get_store().session(sessionmaker) as session:
        rows = await RunLogRepository(session).aggregate_llm()
        agg = next(((d, m, c, co) for d, m, c, co in rows if m == "deepseek-agg"), None)
        assert agg is not None
        assert agg[2] >= 2  # 本测试两行保证下限
        assert agg[3] >= 0.8  # 0.5 + 0.3
