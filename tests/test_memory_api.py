"""T3 记忆域测试（DB-backed）：卡片 CRUD/importance 排序/版本只增/软删。"""
from __future__ import annotations

import uuid

import pytest

from app.core.errors import AppError
from app.services.memory import MemoryService
from app.storage.file.store import get_store
from app.storage.models import User


@pytest.fixture
async def memory_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"mem_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        other_user = User(
            username=f"mem2_{uid}", password_hash="hashed", name="T2", role="admin", org_id=uuid.UUID(int=0)
        )
        session.add(other_user)
        await session.commit()
    yield user, other_user


async def test_create_card_note_and_json_card(memory_fixture):
    user, other = memory_fixture
    async with get_store().session() as session:
        svc = MemoryService()
        note = await svc.create_card(
            session, user.id, card_type="note", title="偏好", body={"text": "喜欢喝茶"}, tags=["偏好"]
        )
        assert note.card_type == "note"
        assert note.content == {"text": "喜欢喝茶"}
        assert note.importance == 0.0  # 默认
        assert note.source == "manual"
        assert note.current_version == 1
        jc = await svc.create_card(
            session, user.id, card_type="json_card", title="画像", body={"person": {"name": "张三"}}
        )
        assert jc.content == {"person": {"name": "张三"}}


async def test_list_cards_sorted_by_importance_desc(memory_fixture):
    user, other = memory_fixture
    async with get_store().session() as session:
        svc = MemoryService()
        await svc.create_card(session, user.id, "note", "低", {"text": "x"}, importance=0.2)
        await svc.create_card(session, user.id, "note", "高", {"text": "y"}, importance=0.9)
        await svc.create_card(session, user.id, "note", "中", {"text": "z"}, importance=0.5)
        cards = await svc.list_cards(session, user.id)
        assert [c.title for c in cards] == ["高", "中", "低"]


async def test_version_append_only(memory_fixture):
    user, other = memory_fixture
    async with get_store().session() as session:
        svc = MemoryService()
        card = await svc.create_card(session, user.id, "note", "卡", {"text": "v1"})
        await svc.update_card(session, user.id, card.id, content={"text": "v2"}, importance=0.8)
        await svc.update_card(session, user.id, card.id, content={"text": "v3"})
        versions = await svc.list_versions(session, user.id, card.id)
        assert len(versions) == 3  # v1 + v2 + v3（只增不覆盖）
        assert versions[-1]["version"] == 3
        card2 = await svc.get_card(session, user.id, card.id)
        assert card2.current_version == 3
        assert card2.content == {"text": "v3"}
        assert card2.importance == 0.8


async def test_soft_delete_card(memory_fixture):
    user, other = memory_fixture
    async with get_store().session() as session:
        svc = MemoryService()
        card = await svc.create_card(session, user.id, "note", "卡", {"text": "x"})
        await svc.soft_delete(session, user.id, card.id)
        with pytest.raises(AppError) as exc:
            await svc.get_card(session, user.id, card.id)
        assert exc.value.code == 40409
        cards = await svc.list_cards(session, user.id)
        assert cards == []  # 软删后列表不可见


async def test_other_user_card_40409(memory_fixture):
    user, other = memory_fixture
    async with get_store().session() as session:
        svc = MemoryService()
        card = await svc.create_card(session, user.id, "note", "卡", {"text": "x"})
        with pytest.raises(AppError) as exc:
            await svc.get_card(session, other.id, card.id)  # 他人卡片不可见
        assert exc.value.code == 40409
