"""M7-B 工作区会话隔离测试：list 按 workspace_id 过滤（None=排除工作区 / 有值=命中工作区）。"""
from __future__ import annotations

import uuid

import pytest

from app.services.conversation import ConversationService
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, User
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def conv_ws_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(
            username=f"convws_{uid}", password_hash="hashed", name="C", role="admin", org_id=uuid.UUID(int=0)
        )
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="会话助手", model="fake", system_prompt="x",
            tools=[], max_steps=5, status="published"
        )
        session.add(agent)
        await session.flush()
        ws_id = uuid.uuid4()
        from app.storage.repositories.conversation import ConversationRepository

        normal = await ConversationRepository(session).create(
            user_id=user.id, agent_id=agent.id, title="普通会话"
        )
        ws_conv = await ConversationRepository(session).create(
            user_id=user.id, agent_id=agent.id, title="工作区会话", workspace_id=ws_id
        )
        await session.commit()
    yield user, ws_id, normal, ws_conv


async def test_list_excludes_workspace_conversations_by_default(conv_ws_fixture):
    user, ws_id, normal, ws_conv = conv_ws_fixture
    async with get_store().session() as session:
        data = await ConversationService().list(session, user.id, 1, 20, workspace_id=None)
        ids = [c["id"] for c in data["items"]]
        assert str(normal.id) in ids
        assert str(ws_conv.id) not in ids
        assert data["total"] == 1


async def test_list_filters_to_workspace(conv_ws_fixture):
    user, ws_id, normal, ws_conv = conv_ws_fixture
    async with get_store().session() as session:
        data = await ConversationService().list(session, user.id, 1, 20, workspace_id=ws_id)
        ids = [c["id"] for c in data["items"]]
        assert str(ws_conv.id) in ids
        assert str(normal.id) not in ids
        assert data["total"] == 1
        assert data["items"][0]["workspace_id"] == str(ws_id)
