"""工作区聊天文件引用的 schema、路径边界与轻量消息持久化回归。"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.schemas.chat import ChatMessageInput
from app.core.errors import AppError
from app.services.serializers import serialize_message
from app.services.workspace import read_file_ref_bytes, resolve_file_ref_path
from app.storage.file.store import get_store
from app.storage.models import Conversation, User
from app.storage.repositories.message import MessageRepository


def test_chat_message_accepts_file_refs_and_limits_sources():
    path = "docs/readme.md"
    message = ChatMessageInput(content="请阅读", file_refs=[{"path": path}])
    assert message.file_refs[0].path == path
    with pytest.raises(ValidationError):
        ChatMessageInput(content="x", file_refs=[{"path": ""}])
    with pytest.raises(ValidationError):
        ChatMessageInput(content="x", file_refs=[{"path": "x"}] * 11)
    with pytest.raises(ValidationError):
        ChatMessageInput(content="x", file_refs=[{"path": "x", "extra": "forbidden"}])
    with pytest.raises(ValidationError):
        ChatMessageInput(content="x", file_refs=[{"path": "x" * 1025}])


def test_file_ref_path_rejects_absolute_traversal_and_non_files(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "docs" / "readme.md"
    target.parent.mkdir()
    target.write_text("nonce", encoding="utf-8")
    canonical, resolved = resolve_file_ref_path(root, "docs\\readme.md")
    assert canonical == "docs/readme.md" and resolved == target.resolve()

    bad_paths = ["../secret.txt", str(target), "C:\\secret.txt", "docs", "missing.md"]
    (root / "docs").mkdir(exist_ok=True)
    for path in bad_paths:
        with pytest.raises(AppError) as exc:
            resolve_file_ref_path(root, path)
        assert exc.value.code == 40015


def test_file_ref_read_revalidates_before_open(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "notes.txt"
    target.write_bytes(b"nonce")
    assert read_file_ref_bytes(root, "notes.txt") == b"nonce"

    link = root / "outside.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不允许创建测试符号链接")
    with pytest.raises(AppError) as exc:
        read_file_ref_bytes(root, "outside.txt")
    assert exc.value.code == 40015


@pytest.mark.asyncio
async def test_message_file_refs_roundtrip(_filestore):
    user = User(username=f"ref_{uuid.uuid4().hex[:8]}", password_hash="x", name="R", role="admin")
    conversation = Conversation(user_id=user.id, agent_id=uuid.uuid4(), title="refs")
    get_store().table("conversations").register(conversation)
    await get_store().table("conversations").flush()
    message = await MessageRepository().create(
        conversation_id=conversation.id,
        role="user",
        content="请阅读",
        file_refs=[{"path": "docs/readme.md"}],
    )
    rows = await MessageRepository().list_by_conversation(conversation.id)
    assert rows[0].file_refs == [{"path": "docs/readme.md"}]
    assert serialize_message(message)["file_refs"] == [{"path": "docs/readme.md"}]
