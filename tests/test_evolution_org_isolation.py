"""M6-2 候选区 org 隔离测试（DB-backed）：跨 org 候选不可见/不可操作（40401）。"""
from __future__ import annotations

import uuid

import pytest

from app.core.errors import AppError
from app.core.security import hash_password
from app.orchestration.graph import build_graph
from app.services.evolution import EvolutionService
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Org, User
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def two_org_evo_fixture():
    engine, sessionmaker = init_db()
    async with get_store().session(sessionmaker) as session:
        org_a = Org(name=f"evo隔离-A-{uuid.uuid4().hex[:8]}")
        org_b = Org(name=f"evo隔离-B-{uuid.uuid4().hex[:8]}")
        session.add_all([org_a, org_b])
        await session.flush()
        user_a = User(
            username=f"evoa_{uuid.uuid4().hex[:6]}", password_hash=hash_password("x"),
            name="A", role="admin", org_id=org_a.id,
        )
        user_b = User(
            username=f"evob_{uuid.uuid4().hex[:6]}", password_hash=hash_password("x"),
            name="B", role="admin", org_id=org_b.id,
        )
        session.add_all([user_a, user_b])
        for org in (org_a, org_b):
            session.add(
                AgentConfig(
                    org_id=org.id, name="通用助手", model="fake", system_prompt="原始提示词",
                    tools=[], max_steps=5, status="published", is_default=True, current_version=1,
                )
            )
        await session.commit()
    yield sessionmaker, user_a, user_b
    await engine.dispose()


async def test_candidate_org_isolation(two_org_evo_fixture):
    sessionmaker, user_a, user_b = two_org_evo_fixture
    svc = EvolutionService()
    async with get_store().session(sessionmaker) as session:
        c_b = await svc.create_candidate(session, user_b, title="B 组织候选", change_type="prompt")
        c_b_id = c_b.id
    async with get_store().session(sessionmaker) as session:
        # A 列表不可见 B 候选
        data_a = await svc.list_candidates(session, user_a, page=1, page_size=100)
        assert str(c_b_id) not in {it["id"] for it in data_a["items"]}
        # A get B 候选 → 40401
        with pytest.raises(AppError) as exc:
            await svc.get_candidate_owned(session, user_a, c_b_id)
        assert exc.value.code == 40401
        # A 对 B 候选动作 → 40401
        graph = build_graph()
        for action in ("reject", "publish", "rollback", "validate"):
            fn = getattr(svc, f"{action}_candidate")
            args = (session, user_a, c_b_id)
            if action == "validate":
                args = (session, user_a, c_b_id, graph)
            with pytest.raises(AppError) as exc:
                await fn(*args)
            assert exc.value.code == 40401
