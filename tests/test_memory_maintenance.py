"""T4 maintenance 测试（DB-backed，FakeChatModel 注入）：LLM 整理 create/update/delete、
围栏 JSON 提取、非法 JSON/LLM 异常 → 60001、importance clamp。
"""
from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.core.errors import AppError
from app.core.security import hash_password
from app.services.memory import MemoryService, _extract_json, run_maintenance
from app.storage.db import init_db
from app.storage.models import Org, User
from app.storage.models.memory import LongTermMemoryVersion
from tests.conftest import requires_db

pytestmark = requires_db


class FakeMaintainModel:
    def __init__(self, content: str, *, raise_error: bool = False) -> None:
        self.content = content
        self.raise_error = raise_error

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        if self.raise_error:
            raise RuntimeError("LLM down")
        return AIMessage(content=self.content)


@pytest.fixture
async def maint_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-maint-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"maint_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.commit()
    yield sessionmaker, user
    await engine.dispose()


def test_extract_json_plain_and_fenced():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('前缀 {"a": 1} 后缀') == {"a": 1}
    with pytest.raises(ValueError):
        _extract_json("不是 JSON")


async def test_maintenance_applies_plan(maint_fixture):
    sessionmaker, user = maint_fixture
    async with sessionmaker() as session:
        svc = MemoryService()
        keep = await svc.create_card(session, user.id, "note", "保留", {"text": "keep"})
        upd = await svc.create_card(session, user.id, "note", "更新", {"text": "old"}, importance=0.3)
        dele = await svc.create_card(session, user.id, "note", "删除", {"text": "bye"})
        await svc.record_trace(session, user.id, role="user", content="用户说喜欢喝咖啡", trace_id="t1")

        plan = {
            "keep": [str(keep.id)],
            "update": [{"id": str(upd.id), "content": {"text": "new"}, "importance": 0.9}],
            "create": [{"content": {"text": "新卡片"}, "importance": 0.7, "card_type": "note"}],
            "delete": [str(dele.id)],
        }
        result = await run_maintenance(session, user.id, model=FakeMaintainModel(json.dumps(plan)))
        assert result["cards_created"] == 1
        assert result["cards_updated"] == 1
        # keep 不变
        assert (await svc.get_card(session, user.id, keep.id)).content == {"text": "keep"}
        # update → 新版本
        upd2 = await svc.get_card(session, user.id, upd.id)
        assert upd2.content == {"text": "new"}
        assert upd2.importance == 0.9
        assert upd2.current_version == 2
        versions = await svc.list_versions(session, user.id, upd.id)
        assert len(versions) == 2
        # create → source=maintenance
        cards = await svc.list_cards(session, user.id)
        created = [c for c in cards if c.source == "maintenance"]
        assert len(created) == 1 and created[0].content == {"text": "新卡片"}
        # delete → 软删
        with pytest.raises(AppError) as exc:
            await svc.get_card(session, user.id, dele.id)
        assert exc.value.code == 40409


async def test_maintenance_fenced_json(maint_fixture):
    sessionmaker, user = maint_fixture
    async with sessionmaker() as session:
        plan = {"keep": [], "update": [], "create": [], "delete": []}
        result = await run_maintenance(
            session, user.id, model=FakeMaintainModel(f"```json\n{json.dumps(plan)}\n```")
        )
        assert result["cards_created"] == 0


async def test_maintenance_invalid_json_60001(maint_fixture):
    sessionmaker, user = maint_fixture
    async with sessionmaker() as session:
        with pytest.raises(AppError) as exc:
            await run_maintenance(session, user.id, model=FakeMaintainModel("这不是 JSON"))
        assert exc.value.code == 60001
        assert exc.value.retryable is True


async def test_maintenance_llm_error_60001(maint_fixture):
    sessionmaker, user = maint_fixture
    async with sessionmaker() as session:
        with pytest.raises(AppError) as exc:
            await run_maintenance(session, user.id, model=FakeMaintainModel("{}", raise_error=True))
        assert exc.value.code == 60001


async def test_maintenance_invalid_update_id_60001(maint_fixture):
    """C2/S4：LLM 输出合法 JSON 但 update id 非法 UUID → 60001 retryable（非裸 500）。"""
    sessionmaker, user = maint_fixture
    async with sessionmaker() as session:
        plan = {"update": [{"id": "not-a-uuid", "content": {"text": "x"}}], "create": [], "delete": []}
        with pytest.raises(AppError) as exc:
            await run_maintenance(session, user.id, model=FakeMaintainModel(json.dumps(plan)))
        assert exc.value.code == 60001
        assert exc.value.retryable is True


async def test_maintenance_version_conflict_60001(maint_fixture):
    """C4：并发写版本撞 UNIQUE(memory_id, version) → 60001 retryable（IntegrityError 在 commit 处）。"""
    sessionmaker, user = maint_fixture
    async with sessionmaker() as session:
        svc = MemoryService()
        card = await svc.create_card(session, user.id, "note", "并发", {"text": "v1"})
        # 模拟另一 maintenance 已写入 version=2
        session.add(
            LongTermMemoryVersion(memory_id=card.id, version=2, content={"text": "外部 v2"}, importance=0.5)
        )
        await session.commit()
    async with sessionmaker() as session:
        plan = {"update": [{"id": str(card.id), "content": {"text": "本会话 v2"}, "importance": 0.8}]}
        with pytest.raises(AppError) as exc:
            await run_maintenance(session, user.id, model=FakeMaintainModel(json.dumps(plan)))
        assert exc.value.code == 60001
        assert exc.value.retryable is True


async def test_maintenance_importance_clamped(maint_fixture):
    sessionmaker, user = maint_fixture
    async with sessionmaker() as session:
        plan = {
            "keep": [],
            "update": [],
            "create": [{"content": {"text": "x"}, "importance": 5.0, "card_type": "note"}],
            "delete": [],
        }
        await run_maintenance(session, user.id, model=FakeMaintainModel(json.dumps(plan)))
        cards = await MemoryService().list_cards(session, user.id)
        assert cards[0].importance == 1.0  # clamp 到 [0,1]
