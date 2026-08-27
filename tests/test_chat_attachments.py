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
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Conversation, User
from app.storage.repositories.attachment import AttachmentRepository
from app.storage.repositories.message import MessageRepository


class FakeChatModel:
    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="已收到，这是回复。")


@pytest.fixture
async def chat_att_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"ca_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="附件测试助手", model="fake", system_prompt="你是测试助手。",
            tools=[], max_steps=5, status="published",
        )
        session.add(agent)
        await session.flush()
        conv = Conversation(user_id=user.id, agent_id=agent.id, title="附件会话")
        session.add(conv)
        await session.commit()
    yield user, agent, conv


async def _run_chat(chat_fixture, content: str, attachments: list[str] | None = None) -> list[str]:
    user, agent, conv = chat_fixture
    graph = build_graph()
    frames = []
    async with get_store().session() as session:
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
    user, agent, conv = chat_att_fixture
    # 先上传一个附件
    async with get_store().session() as session:
        att = await AttachmentService().save_upload(session, user, "a.txt", "text/plain", b"hello")
        att_id = att.id
    await _run_chat(chat_att_fixture, "看下这个附件", attachments=[str(att_id)])
    async with get_store().session() as session:
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
    user, agent, conv = chat_att_fixture
    await _run_chat(chat_att_fixture, "没有附件的消息")
    async with get_store().session() as session:
        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        assert all(m.attachments is None or m.attachments == [] for m in msgs)


# ---- 多模态（2026-08-27）：图片载荷 → 水合 → 无 b64 泄漏 ----


class CapturingModel:
    """捕获 bind_tools 后收到的 messages，供断言水合/降级；其余同 FakeChatModel。"""

    def __init__(self) -> None:
        self.seen: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.seen.append([m.model_copy(deep=True) for m in messages])
        return AIMessage(content="已收到，这是回复。")


async def test_image_attachment_non_vision_degrades_with_note(chat_att_fixture):
    """非视觉模型带图：链路跑通、落库仍纯 str+引用、模型收到注记前缀纯文本（无 ref 块泄漏）。"""
    user, agent, conv = chat_att_fixture
    async with get_store().session() as session:
        att = await AttachmentService().save_upload(session, user, "a.png", "image/png", b"\x89PNG fake")
        att_id = str(att.id)
    model = CapturingModel()
    frames = []
    async with get_store().session() as session:
        async for frame in chat_stream_events(
            db=session, graph=graph_local(), conversation=conv, agent=agent, user=user,
            content="这是什么图？", attachments=[att_id], trace_id="trace-mm",
            model_override=model, attachment_mimes={att_id: "image/png"},
        ):
            frames.append(frame)
    # 落库不变：用户消息 content 纯 str + attachments 引用
    async with get_store().session() as session:
        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        user_msg = next(m for m in msgs if m.role == "user")
        assert isinstance(user_msg.content, str) and user_msg.content == "这是什么图？"
        assert user_msg.attachments == [{"attachment_id": att_id}]
    # 模型收到的是「注记前缀 + 原文」纯文本（fake 非 vision pattern、未声明）
    first_human = next(m for m in model.seen[0] if m.type == "human")
    assert isinstance(first_human.content, str)
    assert "不支持读取图片" in first_human.content
    assert "已被忽略" in first_human.content
    assert first_human.content.endswith("这是什么图？")
    # SSE 正常 done
    assert any("done" in f for f in frames)


async def test_image_attachment_vision_hydrates_block_and_no_b64_in_checkpoint(chat_att_fixture):
    """声明 vision 的模型带图：模型收到标准 image 块（b64）；checkpoint 文件不含 b64（尺寸上界）。"""
    from pathlib import Path

    from app.core.config import get_settings

    user, agent, conv = chat_att_fixture
    png_bytes = b"\x89PNG" + b"x" * 512  # 小图，2KB 内
    async with get_store().session() as session:
        att = await AttachmentService().save_upload(session, user, "a.png", "image/png", png_bytes)
        att_id = str(att.id)
    settings = get_settings()
    # agent 钉死 gpt-4o（pattern 命中）→ vision=True（声明 None 回落 pattern）
    agent_gpt = AgentConfig(
        org_id=uuid.UUID(int=0), name="视觉助手", model="gpt-4o", system_prompt="你是视觉助手。",
        tools=[], max_steps=5, status="published",
    )
    async with get_store().session() as session:
        import app.storage.file.store as store_mod

        store_mod.get_store().table("agents").register(agent_gpt)
        await session.commit()
    model = CapturingModel()
    async with get_store().session() as session:
        async for _ in chat_stream_events(
            db=session, graph=graph_local(), conversation=conv, agent=agent_gpt, user=user,
            content="描述这张图", attachments=[att_id], trace_id="trace-mm-v",
            model_override=model, attachment_mimes={att_id: "image/png"},
        ):
            pass
    # 模型首条 human 含标准 image 块（b64 与源文件一致）
    first_human = next(m for m in model.seen[0] if m.type == "human")
    assert isinstance(first_human.content, list)
    img_blocks = [b for b in first_human.content if b.get("type") == "image"]
    assert len(img_blocks) == 1
    assert img_blocks[0]["source_type"] == "base64"
    assert img_blocks[0]["mime_type"] == "image/png"
    assert img_blocks[0]["data"] == __import__("base64").b64encode(png_bytes).decode("ascii")
    text_blocks = [b for b in first_human.content if b.get("type") == "text"]
    assert text_blocks and text_blocks[-1]["text"] == "描述这张图"  # 图前文后
    # checkpoint 不含 b64（读 thread 目录 JSON 尺寸上界）
    ckpt_dir = Path(settings.agent_data_dir) / "checkpoints"
    ckpt_files = list(ckpt_dir.rglob("*.json")) if ckpt_dir.is_dir() else []
    assert ckpt_files, "checkpoint 应已写盘"
    for f in ckpt_files:
        data = f.read_text(encoding="utf-8", errors="ignore")
        assert "eDk5UE5H" not in data and "\x89PNG" not in data  # b64/原始字节不落盘


def graph_local():
    from app.orchestration.graph import build_graph

    return build_graph()


def test_stream_graph_config_exposes_image_payload():
    """_graph_config 写入 image_payload/current_image_ids/vision（configurable 不落盘由 saver 保证）。"""
    from uuid import uuid4

    from app.core.multimodal import ImagePayload
    from app.orchestration.chat_stream import _graph_config

    cfg = _graph_config(
        thread_id="t", trace_id="tr", assistant_msg_id=uuid4(),
        image_payload={"a": ImagePayload(att_id="a", mime="image/png", data_b64="xx")},
        current_image_ids={"a"}, vision=True,
    )
    c = cfg["configurable"]
    assert c["vision"] is True and c["current_image_ids"] == {"a"}
    assert c["image_payload"]["a"].mime == "image/png"
    # 不传则不带这些键（旧路径零变化）
    cfg2 = _graph_config(thread_id="t", trace_id="tr", assistant_msg_id=uuid4())
    assert "image_payload" not in cfg2["configurable"]
