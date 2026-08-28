"""文档抽取、来源标记、预算和 checkpoint 边界测试。"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage

from app.orchestration.chat_stream import chat_stream_events
from app.orchestration.checkpointer import JsonFileSaver
from app.orchestration.document_context import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    SOURCE_CHAR_LIMIT,
    TOTAL_CHAR_LIMIT,
    extract_document_units,
    render_document_content,
    select_source_text,
)
from app.orchestration.graph import build_graph
from app.services.attachment import AttachmentService
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Conversation, User


def test_utf8_text_and_markdown_extract_without_truncating_at_2000():
    nonce = "唯一附件 nonce：" + ("x" * 2400)
    units = extract_document_units(("\ufeff" + nonce).encode(), "text/markdown", "notes.md")
    assert units[0][1] == nonce


def test_large_source_selection_is_deterministic_and_bounded():
    text = "标题\n" + ("无关内容。" * 5000) + "\n目标 nonce-attachment-42\n" + ("尾部。" * 5000)
    selected = select_source_text(text, "查找 nonce-attachment-42")
    assert "nonce-attachment-42" in selected
    assert len(selected) <= SOURCE_CHAR_LIMIT
    assert CHUNK_SIZE > CHUNK_OVERLAP > 0
    assert select_source_text(text, "查找 nonce-attachment-42") == selected


def test_document_ref_renders_source_marker_and_does_not_leak_when_not_current():
    ref = {
        "type": "document_ref",
        "source_id": "workspace:README.md",
        "kind": "workspace",
        "display_name": "README.md",
        "path": "README.md",
    }
    current = render_document_content(
        [ref, {"type": "text", "text": "请总结"}],
        index={
            "workspace:README.md": {
                "display_name": "README.md", "kind": "workspace", "path": "README.md", "text": "nonce"
            }
        },
        current_ids={"workspace:README.md"},
    )
    assert "nonce" in current[0]["text"]
    assert "[工作区引用: README.md | README.md]" in current[0]["text"]
    historical = render_document_content([ref], index={}, current_ids=set())
    assert "内容不可用" in historical[0]["text"]
    assert "nonce" not in historical[0]["text"]


@pytest.mark.parametrize(
    ("mime", "filename"),
    [
        ("application/pdf", "report.pdf"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "report.docx"),
    ],
)
def test_document_formats_use_real_extractors(mime: str, filename: str):
    """依赖未安装时跳过；安装后验证 PDF 页码和 DOCX 正文都会进入抽取器。"""
    if mime == "application/pdf":
        pypdf = pytest.importorskip("pypdf")
        from io import BytesIO

        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        stream = BytesIO()
        writer.write(stream)
        # 空白页没有文本，但必须能被真实 reader 打开而非 metadata-only 分支。
        assert extract_document_units(stream.getvalue(), mime, filename) == []
    else:
        docx = pytest.importorskip("docx")
        from io import BytesIO

        document = docx.Document()
        document.add_paragraph("docx nonce")
        stream = BytesIO()
        document.save(stream)
        units = extract_document_units(stream.getvalue(), mime, filename)
        assert any("docx nonce" in text for _, text in units)


def test_context_budget_constant_is_explicit():
    assert SOURCE_CHAR_LIMIT == 12_000
    assert TOTAL_CHAR_LIMIT == 48_000


class _CapturingModel:
    def __init__(self) -> None:
        self.seen: list[list] = []

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.seen.append([message.model_copy(deep=True) for message in messages])
        return AIMessage(content="done")


@pytest.mark.asyncio
async def test_attachment_text_reaches_model_without_entering_checkpoint(tmp_path):
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        user = User(username=f"doc_{uid}", name="D", role="admin")
        session.add(user)
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="doc", model="fake", system_prompt="system", tools=[], max_steps=3
        )
        session.add(agent)
        await session.flush()
        conversation = Conversation(user_id=user.id, agent_id=agent.id, title="doc")
        session.add(conversation)
        await session.commit()
        attachment = await AttachmentService().save_upload(
            session, user, "notes.md", "text/markdown", b"document nonce 7f3a"
        )
        attachment_id = str(attachment.id)

    model = _CapturingModel()
    graph = build_graph(JsonFileSaver(tmp_path / "checkpoints"))
    async with get_store().session() as session:
        async for _ in chat_stream_events(
            db=session,
            graph=graph,
            conversation=conversation,
            agent=agent,
            user=user,
            content="请总结附件",
            attachments=[attachment_id],
            trace_id="doc-context",
            model_override=model,
        ):
            pass
    human = next(message for message in model.seen[0] if message.type == "human")
    assert isinstance(human.content, list)
    text = "\n".join(block.get("text", "") for block in human.content if isinstance(block, dict))
    assert "document nonce 7f3a" in text
    assert "[附件: notes.md" in text
    checkpoint = next((tmp_path / "checkpoints").glob("*.json"))
    assert "document nonce 7f3a" not in checkpoint.read_text(encoding="utf-8")
