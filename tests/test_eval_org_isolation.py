"""M6-1 Eval 运行/结果 org 隔离测试（DB-backed）：跨 org run 不可见（40414「不存在或无权访问」口径）。"""
from __future__ import annotations

import uuid

import pytest

from app.core.errors import AppError
from app.core.security import hash_password
from app.services.eval import EvalService
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import Org, User
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def two_org_fixture():
    engine, sessionmaker = init_db()
    async with get_store().session(sessionmaker) as session:
        org_a = Org(name=f"评估隔离-A-{uuid.uuid4().hex[:8]}")
        org_b = Org(name=f"评估隔离-B-{uuid.uuid4().hex[:8]}")
        session.add_all([org_a, org_b])
        await session.flush()
        user_a = User(
            username=f"evala_{uuid.uuid4().hex[:6]}", password_hash=hash_password("x"),
            name="A", role="admin", org_id=org_a.id,
        )
        user_b = User(
            username=f"evalb_{uuid.uuid4().hex[:6]}", password_hash=hash_password("x"),
            name="B", role="admin", org_id=org_b.id,
        )
        session.add_all([user_a, user_b])
        await session.commit()
    yield sessionmaker, user_a, user_b
    await engine.dispose()


async def test_run_org_isolation(two_org_fixture):
    sessionmaker, user_a, user_b = two_org_fixture
    svc = EvalService()
    async with get_store().session(sessionmaker) as session:
        set_a = await svc.create_set(session, user_a, "A 集")
        set_b = await svc.create_set(session, user_b, "B 集")
        run_a = await svc.create_run(session, user_a, set_a.id)
        run_b = await svc.create_run(session, user_b, set_b.id)
        run_a_id, run_b_id = run_a.id, run_b.id
    async with get_store().session(sessionmaker) as session:
        # list_runs 按 org 收敛：A 只见 A 的 run
        runs_a = await svc.list_runs(session, user_a)
        assert str(run_a_id) in {r["id"] for r in runs_a}
        assert str(run_b_id) not in {r["id"] for r in runs_a}
        # get_run_detail 跨 org → 40414
        with pytest.raises(AppError) as exc:
            await svc.get_run_detail(session, user_a, run_b_id)
        assert exc.value.code == 40414
        # pairwise 任一 run 属他 org → 40414
        with pytest.raises(AppError) as exc:
            await svc.pairwise(session, user_a, run_b_id, run_a_id)
        assert exc.value.code == 40414
        with pytest.raises(AppError) as exc:
            await svc.pairwise(session, user_a, run_a_id, run_b_id)
        assert exc.value.code == 40414
