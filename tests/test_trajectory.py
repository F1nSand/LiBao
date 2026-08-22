"""2c trajectory 测试（DB-backed）：消息→节点映射、tool_calls 派生、before_seq/limit 分页、has_more。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services.conversation import ConversationService
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Conversation, User
from app.storage.repositories.message import MessageRepository
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def traj_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"traj_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="轨迹助手", model="fake", system_prompt="x",
            tools=[], max_steps=5, status="published"
        )
        session.add(agent)
        await session.flush()
        conv = Conversation(user_id=user.id, agent_id=agent.id, title="轨迹会话")
        session.add(conv)
        await session.flush()
        repo = MessageRepository(session)
        # 显式递增 created_at（同 commit 的 server_default now() 会并列，排序不稳定——确定性修复）
        base = datetime(2026, 1, 1, tzinfo=UTC)
        m1 = await repo.create(conversation_id=conv.id, role="user", content="第一条", trace_id="t1")
        m1.created_at = base
        m2 = await repo.create(
            conversation_id=conv.id,
            role="assistant",
            content="回复",
            tool_calls=[
                {
                    "tool_call_id": "c1",
                    "tool_name": "time_now",
                    "input": {},
                    "output": {"x": 1},
                    "ok": True,
                    "duration_ms": 5,
                    "position": 0,
                }
            ],
            token_usage={"total_tokens": 10},
            trace_id="t2",
        )
        m2.created_at = base + timedelta(seconds=1)
        m3 = await repo.create(conversation_id=conv.id, role="user", content="第二条", trace_id="t3")
        m3.created_at = base + timedelta(seconds=2)
        await session.commit()
    yield user, conv


async def test_trajectory_mapping_and_pagination(traj_fixture):
    user, conv = traj_fixture
    async with get_store().session() as session:
        data = await ConversationService().trajectory(session, conv)
        assert data["conversation_id"] == str(conv.id)
        assert data["has_more"] is False
        nodes = data["nodes"]
        assert [n["kind"] for n in nodes] == ["user", "assistant", "user"]
        assert nodes[0]["seq"] == 1 and nodes[0]["content"] == "第一条"
        assert nodes[0]["trace_id"] == "t1"
        assert nodes[0]["time"] > 0
        assert nodes[1]["seq"] == 2 and nodes[1]["kind"] == "assistant"
        assert nodes[1]["tool_calls"][0]["tool_name"] == "time_now"
        assert nodes[1]["tool_calls"][0]["position"] == 0
        assert nodes[1]["token_usage"] == {"total_tokens": 10}
        assert nodes[1]["thinking"] is None and nodes[1]["diff"] is None

        # before_seq 分页：seq<3 的候选是 [1,2]，取末尾 limit=1 → [2]，has_more 真
        data2 = await ConversationService().trajectory(session, conv, before_seq=3, limit=1)
        assert [n["seq"] for n in data2["nodes"]] == [2]
        assert data2["has_more"] is True
