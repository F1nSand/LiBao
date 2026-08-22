"""T10 消息 attachments 链路测试（DB-backed，FakeChatModel）。

覆盖：带附件发消息 → 用户消息 attachments=[id] + 附件回填；纯文本消息落 messages；chat_stream_events 全链路。
"""
from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.api.schemas.chat import ChatMessageInput
from app.orchestration.chat_stream import chat_stream_events
from app.orchestration.graph import build_graph
from app.services.attachment import AttachmentService
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Conversation, Org, User
from app.storage.repositories.attachment import AttachmentRepository
from app.storage.repositories.message import MessageRepository
from tests.conftest import requires_db

pytestmark = requires_db


class FakeChatModel:
    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="已收到，这是回复。")


@pytest.fixture
async def chat_att_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-ca-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"ca_{uid}", password_hash="hashed", name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="附件测试助手", model="fake", system_prompt="你是测试助手。",
            tools=[], max_steps=5, status="published",
        )
        session.add(agent)
        await session.flush()
        conv = Conversation(user_id=user.id, agent_id=agent.id, title="附件会话")
        session.add(conv)
        await session.commit()
    yield sessionmaker, org, user, agent, conv
    await engine.dispose()


async def _run_chat(chat_fixture, content: str, attachments: list[str] | None = None) -> list[str]:
    sessionmaker, org, user, agent, conv = chat_fixture
    graph = build_graph()
    frames = []
    async with get_store().session(sessionmaker) as session:
        async for frame in chat_stream_events(
            db=session,
            graph=graph,
            conversation=conv,
            agent=agent,
            user=user,
            content=content,
            attachments=attachments,
            trace_id="trace-ca",
            model_override=FakeChatModel(),
        ):
            frames.append(frame)
    return frames


async def test_chat_with_attachment_links(chat_att_fixture):
    sessionmaker, org, user, agent, conv = chat_att_fixture
    # 先上传一个附件
    async with get_store().session(sessionmaker) as session:
        att = await AttachmentService().save_upload(session, user, "a.txt", "text/plain", b"hello")
        att_id = att.id
    await _run_chat(chat_att_fixture, "看下这个附件", attachments=[str(att_id)])
    async with get_store().session(sessionmaker) as session:
        # 用户消息带 attachments
        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        user_msg = next(m for m in msgs if m.role == "user")
        assert user_msg.attachments == [{"attachment_id": str(att_id)}]
        # 附件回填 conversation_id/message_id
        att = await AttachmentRepository(session).get(user.id, att_id)
        assert att.conversation_id == conv.id
        assert att.message_id == user_msg.id


def test_chat_message_input_attachments_uuid_validation():
    """S9：attachments 非法 UUID → pydantic ValidationError（路由自然 422，而非 uuid.UUID 裸抛 500）。"""
    m = ChatMessageInput(content="x", attachments=[uuid.uuid4()])
    assert len(m.attachments) == 1
    with pytest.raises(ValidationError):
        ChatMessageInput(content="x", attachments=["not-a-uuid"])


async def test_plain_text_persists_message(chat_att_fixture):
    sessionmaker, org, user, agent, conv = chat_att_fixture
    await _run_chat(chat_att_fixture, "没有附件的消息")
    async with get_store().session(sessionmaker) as session:
        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        assert all(m.attachments is None or m.attachments == [] for m in msgs)
