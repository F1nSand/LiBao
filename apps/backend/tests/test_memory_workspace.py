"""M7-B 工作区记忆隔离测试：list_cards 按 workspace_id 过滤。"""
from __future__ import annotations

import uuid

import pytest

from app.storage.file.store import get_store
from app.storage.models import User
from app.storage.repositories.memory import MemoryRepository
from app.tools.builtin import register_builtin_tools


@pytest.fixture
async def mem_fixture():
    register_builtin_tools()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"mem_{uid}", password_hash="hashed", name="M", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.commit()
    yield user


async def test_list_cards_workspace_filter(mem_fixture):
    user = mem_fixture
    ws_id = uuid.uuid4()
    async with get_store().session() as session:
        repo = MemoryRepository(session)
        # 个人记忆（workspace_id NULL）+ 工作区记忆
        await repo.create_card(user_id=user.id, card_type="note", content={"text": "personal"})
        await repo.create_card(
            user_id=user.id, card_type="note", content={"text": "ws"}, workspace_id=ws_id
        )
        await session.commit()
        # 普通上下文 → 只取个人
        personal = await repo.list_cards(user.id, limit=10, workspace_id=None)
        assert [c.content["text"] for c in personal] == ["personal"]
        # 工作区上下文 → 工作区 ∪ 个人
        both = await repo.list_cards(user.id, limit=10, workspace_id=ws_id)
        texts = {c.content["text"] for c in both}
        assert texts == {"personal", "ws"}
