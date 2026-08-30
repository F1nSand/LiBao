from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from app.checkpoints.restore import CheckpointRestoreService
from app.checkpoints.service import CheckpointService
from app.checkpoints.store import CodeCheckpointStore
from app.core.errors import AppError
from app.storage.models.conversation import Conversation
from app.storage.repositories.attachment import AttachmentRepository
from app.storage.repositories.message import MessageRepository


class _Db:
    async def commit(self) -> None:
        return None


async def _checkpoint_with_message(
    checkpoint_service: CheckpointService,
    conversation: Conversation,
    *,
    content: str,
    anchor_message_head_id: uuid.UUID | None,
    history_parent_id: uuid.UUID | None,
    attachments: list[dict] | None = None,
    file_refs: list[dict] | None = None,
    workspace_identity: str = "session:test",
) -> tuple[object, object]:
    user_message_id = uuid.uuid4()
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation.id,
        user_message_id=user_message_id,
        workspace_identity=workspace_identity,
        anchor_message_head_id=anchor_message_head_id,
        graph_parent_checkpoint_id="graph-parent" if anchor_message_head_id else None,
        graph_parent_bound=True,
    )
    message = await MessageRepository().create(
        message_id=user_message_id,
        conversation_id=conversation.id,
        role="user",
        content=content,
        attachments=attachments,
        file_refs=file_refs,
        checkpoint_id=checkpoint.id,
        history_parent_id=history_parent_id,
    )
    return checkpoint, message


def _conversation(conversation_id: uuid.UUID) -> Conversation:
    return Conversation(user_id=uuid.uuid4(), agent_id=uuid.uuid4(), id=conversation_id)


@pytest.mark.asyncio
async def test_preview_and_execute_restores_bytes(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        workspace_identity=f"session:{tmp_path / 'workspace'}",
        anchor_message_head_id=None,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_bytes(b"before\n")
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before\n",
        tool_call_id="call",
        planned_after_sha256=hashlib.sha256(b"after\n").hexdigest(),
    )
    target.write_bytes(b"after\n")
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=hashlib.sha256(b"after\n").hexdigest(),
    )

    conversation = _conversation(conversation_id)
    service = CheckpointRestoreService(checkpoint_service)
    preview = await service.preview_checkpoint(
        _Db(),
        conversation,
        target_checkpoint_id=checkpoint.id,
        mode="code_only",
        workspace_root=str(workspace),
    )
    assert preview["files"][0]["diff"]
    result = await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))

    assert result["status"] == "completed"
    assert target.read_bytes() == b"before\n"
    assert len(await checkpoint_store.list_operations(conversation_id)) == 1


@pytest.mark.asyncio
async def test_manual_conflict_is_skipped(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    conversation = _conversation(conversation_id)
    checkpoint, user_message = await _checkpoint_with_message(
        checkpoint_service,
        conversation,
        content="包含手动冲突",
        anchor_message_head_id=None,
        history_parent_id=None,
        workspace_identity=f"session:{tmp_path / 'workspace'}",
    )
    conversation.active_message_head_id = user_message.id
    conversation.message_cursor_initialized = True
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_text("before", encoding="utf-8")
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before",
        tool_call_id="call",
        planned_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    target.write_text("after", encoding="utf-8")
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    target.write_text("manual edit", encoding="utf-8")

    service = CheckpointRestoreService(checkpoint_service)
    preview = await service.preview_checkpoint(
        _Db(),
        conversation,
        target_checkpoint_id=checkpoint.id,
        mode="both",
        workspace_root=str(workspace),
    )
    result = await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))

    assert result["status"] == "partial"
    assert result["skipped_conflicts"] == ["note.txt"]
    assert target.read_text(encoding="utf-8") == "manual edit"


@pytest.mark.asyncio
async def test_rollback_can_switch_back_to_a_later_checkpoint(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"

    async def mutate_before_turn(before: bytes, after: bytes) -> object:
        target.write_bytes(before)
        checkpoint = await checkpoint_service.create_anchor(
            conversation_id=conversation_id,
            user_message_id=uuid.uuid4(),
            workspace_identity=f"session:{workspace}",
            anchor_message_head_id=None,
        )
        await checkpoint_store.prepare_file(
            conversation_id,
            checkpoint.id,
            "note.txt",
            before,
            tool_call_id=str(uuid.uuid4()),
            planned_after_sha256=hashlib.sha256(after).hexdigest(),
        )
        target.write_bytes(after)
        await checkpoint_store.finalize_file(
            conversation_id,
            checkpoint.id,
            "note.txt",
            final_after_sha256=hashlib.sha256(after).hexdigest(),
        )
        return checkpoint

    await mutate_before_turn(b"a", b"b")
    checkpoint_b = await mutate_before_turn(b"b", b"c")
    checkpoint_c = await mutate_before_turn(b"c", b"d")

    service = CheckpointRestoreService(checkpoint_service)
    conversation = _conversation(conversation_id)
    first_preview = await service.preview_checkpoint(
        _Db(), conversation, target_checkpoint_id=checkpoint_b.id, mode="code_only", workspace_root=str(workspace)
    )
    await service.execute_preview(_Db(), conversation, uuid.UUID(first_preview["preview_id"]))
    assert target.read_bytes() == b"b"

    second_preview = await service.preview_checkpoint(
        _Db(), conversation, target_checkpoint_id=checkpoint_c.id, mode="code_only", workspace_root=str(workspace)
    )
    assert second_preview["files"][0]["conflict"] is False
    await service.execute_preview(_Db(), conversation, uuid.UUID(second_preview["preview_id"]))
    assert target.read_bytes() == b"c"


@pytest.mark.asyncio
async def test_conversation_only_preview_ignores_workspace_identity_mismatch(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    conversation = _conversation(conversation_id)
    checkpoint, _ = await _checkpoint_with_message(
        checkpoint_service,
        conversation,
        content="可回滚",
        anchor_message_head_id=None,
        history_parent_id=None,
    )
    checkpoint.workspace_identity = "foreign:/a/different/root"

    service = CheckpointRestoreService(checkpoint_service)
    preview = await service.preview_checkpoint(
        _Db(),
        conversation,
        target_checkpoint_id=checkpoint.id,
        mode="conversation_only",
        workspace_root=None,
    )

    assert preview["files"] == []
    result = await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))
    assert result["status"] == "completed"
    assert result["restored_files"] == 0


@pytest.mark.asyncio
async def test_conversation_modes_withdraw_target_to_anchor_and_return_full_draft(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation = _conversation(uuid.uuid4())

    cp1, u1 = await _checkpoint_with_message(
        checkpoint_service,
        conversation,
        content="第一条",
        anchor_message_head_id=None,
        history_parent_id=None,
    )
    a1 = await MessageRepository().create(
        conversation_id=conversation.id,
        role="assistant",
        content="第一条回复",
        parent_id=u1.id,
        history_parent_id=u1.id,
    )
    cp2, u2 = await _checkpoint_with_message(
        checkpoint_service,
        conversation,
        content="第二条",
        anchor_message_head_id=a1.id,
        history_parent_id=a1.id,
    )
    a2 = await MessageRepository().create(
        conversation_id=conversation.id,
        role="assistant",
        content="第二条回复",
        parent_id=u2.id,
        history_parent_id=u2.id,
    )
    conversation.active_message_head_id = a2.id
    conversation.message_cursor_initialized = True
    conversation.active_graph_checkpoint_id = "graph-after-2"
    conversation.graph_cursor_initialized = True
    conversation.active_code_node_id = cp2.id
    conversation.history_revision = 4

    service = CheckpointRestoreService(checkpoint_service)
    preview = await service.preview_checkpoint(
        _Db(), conversation, target_checkpoint_id=cp2.id, mode="conversation_only", workspace_root=None
    )

    assert preview["target"]["message_id"] == str(u2.id)
    assert preview["conversation"] == {
        "action": "withdraw_from_target",
        "active_message_head_after_id": str(a1.id),
        "withdrawn_from_message_id": str(u2.id),
        "hidden_message_count": 2,
        "draft": {
            "source_message_id": str(u2.id),
            "content": "第二条",
            "attachments": [],
            "file_refs": [],
        },
    }

    result = await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))

    assert result["conversation"] == preview["conversation"]
    assert conversation.active_message_head_id == a1.id
    active = await MessageRepository().list_active(
        conversation.id,
        conversation.active_message_head_id,
        cursor_initialized=conversation.message_cursor_initialized,
        limit=None,
        offset=0,
    )
    assert [message.id for message in active] == [u1.id, a1.id]


@pytest.mark.asyncio
async def test_withdraw_first_user_message_leaves_empty_active_history_and_trajectory(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation = _conversation(uuid.uuid4())
    checkpoint, user_message = await _checkpoint_with_message(
        checkpoint_service,
        conversation,
        content="首条输入",
        anchor_message_head_id=None,
        history_parent_id=None,
    )
    assistant = await MessageRepository().create(
        conversation_id=conversation.id,
        role="assistant",
        content="首条回复",
        parent_id=user_message.id,
        history_parent_id=user_message.id,
    )
    conversation.active_message_head_id = assistant.id
    conversation.message_cursor_initialized = True
    conversation.history_revision = 2

    service = CheckpointRestoreService(checkpoint_service)
    preview = await service.preview_checkpoint(
        _Db(), conversation, target_checkpoint_id=checkpoint.id, mode="conversation_only", workspace_root=None
    )
    await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))

    assert conversation.active_message_head_id is None
    assert preview["conversation"]["hidden_message_count"] == 2
    assert await MessageRepository().list_active(
        conversation.id, None, cursor_initialized=True, limit=None, offset=0
    ) == []


@pytest.mark.asyncio
async def test_restore_draft_preserves_attachment_metadata_and_availability(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation = _conversation(uuid.uuid4())
    att_repo = AttachmentRepository()
    ready = await att_repo.create(
        user_id=conversation.user_id,
        filename="ready.bin",
        content_type="application/octet-stream",
        size_bytes=7,
        storage_path="ready",
    )
    ready.status = "ready"
    failed = await att_repo.create(
        user_id=conversation.user_id,
        filename="failed.txt",
        content_type="text/plain",
        size_bytes=3,
        storage_path="failed",
    )
    failed.status = "failed"
    missing_id = uuid.uuid4()
    attachment_refs = [
        {
            "attachment_id": str(missing_id),
            "name": "missing.bin",
            "mime_type": "application/octet-stream",
            "size": 10,
            "status": "ready",
        },
        {
            "attachment_id": str(failed.id),
            "name": "failed-old.txt",
            "mime_type": "text/plain",
            "size": 2,
            "status": "ready",
        },
        {
            "attachment_id": str(ready.id),
            "name": "ready-old.bin",
            "mime_type": "application/octet-stream",
            "size": 1,
            "status": "uploaded",
        },
    ]
    checkpoint, user_message = await _checkpoint_with_message(
        checkpoint_service,
        conversation,
        content="带附件输入",
        anchor_message_head_id=None,
        history_parent_id=None,
        attachments=attachment_refs,
        file_refs=[{"path": "src/main.py"}],
    )
    conversation.active_message_head_id = user_message.id
    conversation.message_cursor_initialized = True

    preview = await CheckpointRestoreService(checkpoint_service).preview_checkpoint(
        _Db(), conversation, target_checkpoint_id=checkpoint.id, mode="conversation_only", workspace_root=None
    )
    draft = preview["conversation"]["draft"]

    assert [item["name"] for item in draft["attachments"]] == ["missing.bin", "failed-old.txt", "ready-old.bin"]
    assert draft["attachments"][0]["available"] is False
    assert draft["attachments"][0]["unavailable_reason"]
    assert draft["attachments"][1]["available"] is False
    assert draft["attachments"][1]["status"] == "failed"
    assert draft["attachments"][2]["available"] is True
    assert draft["attachments"][2]["status"] == "ready"
    assert draft["file_refs"] == [{"path": "src/main.py"}]


@pytest.mark.asyncio
async def test_code_modes_still_reject_workspace_identity_mismatch(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity=f"session:{tmp_path / 'other'}",
        anchor_message_head_id=None,
    )
    service = CheckpointRestoreService(checkpoint_service)

    for mode in ("code_only", "both"):
        with pytest.raises(AppError) as exc:
            await service.preview_checkpoint(
                _Db(),
                _conversation(conversation_id),
                target_checkpoint_id=checkpoint.id,
                mode=mode,
                workspace_root=str(workspace),
            )
        assert exc.value.code == 40932


@pytest.mark.asyncio
async def test_execute_rejects_mode_mismatch_without_side_effects(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_bytes(b"after")
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity=f"session:{workspace}",
        anchor_message_head_id=None,
    )
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before",
        tool_call_id="call",
        planned_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    conversation = _conversation(conversation_id)
    service = CheckpointRestoreService(checkpoint_service)
    request_id = uuid.uuid4()
    preview = await service.preview_checkpoint(
        _Db(),
        conversation,
        target_checkpoint_id=checkpoint.id,
        mode="code_only",
        workspace_root=str(workspace),
        client_request_id=request_id,
    )
    before_cursor = _cursor_for_test(conversation)

    with pytest.raises(AppError) as exc:
        await service.execute_preview(
            _Db(),
            conversation,
            uuid.UUID(preview["preview_id"]),
            expected_mode="both",
            client_request_id=request_id,
        )

    assert exc.value.code == 40936
    assert target.read_bytes() == b"after"
    assert _cursor_for_test(conversation) == before_cursor
    assert await checkpoint_store.list_operations(conversation_id) == []

    with pytest.raises(AppError) as request_exc:
        await service.execute_preview(
            _Db(),
            conversation,
            uuid.UUID(preview["preview_id"]),
            expected_mode="code_only",
            client_request_id=uuid.uuid4(),
        )
    assert request_exc.value.code == 40936


@pytest.mark.asyncio
async def test_execute_uses_confirmed_file_plan_and_is_idempotent(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    note = workspace / "note.txt"
    extra = workspace / "extra.txt"
    note.write_bytes(b"after")
    extra.write_bytes(b"extra-after")
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity=f"session:{workspace}",
        anchor_message_head_id=None,
    )
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before",
        tool_call_id="call-note",
        planned_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    service = CheckpointRestoreService(checkpoint_service)
    conversation = _conversation(conversation_id)
    preview = await service.preview_checkpoint(
        _Db(), conversation, target_checkpoint_id=checkpoint.id, mode="code_only", workspace_root=str(workspace)
    )
    # Simulate a late manifest update after the user confirmed the preview.  It
    # must not expand the already-confirmed restore plan.
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "extra.txt",
        b"extra-before",
        tool_call_id="call-extra",
        planned_after_sha256=hashlib.sha256(b"extra-after").hexdigest(),
    )
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "extra.txt",
        final_after_sha256=hashlib.sha256(b"extra-after").hexdigest(),
    )

    first = await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))
    second = await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))

    assert note.read_bytes() == b"before"
    assert extra.read_bytes() == b"extra-after"
    assert second == first
    assert len(await checkpoint_store.list_operations(conversation_id)) == 1


@pytest.mark.asyncio
async def test_preview_cannot_be_executed_by_another_conversation(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity=f"session:{workspace}",
        anchor_message_head_id=None,
    )
    target.write_bytes(b"before")
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before",
        tool_call_id="call",
        planned_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    target.write_bytes(b"after")
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    service = CheckpointRestoreService(checkpoint_service)
    owner = _conversation(conversation_id)
    preview = await service.preview_checkpoint(
        _Db(), owner, target_checkpoint_id=checkpoint.id, mode="code_only", workspace_root=str(workspace)
    )
    other = _conversation(uuid.uuid4())
    before_cursor = _cursor_for_test(other)

    with pytest.raises(AppError) as exc:
        await service.execute_preview(_Db(), other, uuid.UUID(preview["preview_id"]))

    assert exc.value.code == 40935
    assert target.read_bytes() == b"after"
    assert _cursor_for_test(other) == before_cursor


@pytest.mark.asyncio
async def test_operation_before_preview_is_bound_to_owner_conversation(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity=f"session:{workspace}",
        anchor_message_head_id=None,
    )
    target.write_bytes(b"before")
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before",
        tool_call_id="call",
        planned_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    target.write_bytes(b"after")
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    service = CheckpointRestoreService(checkpoint_service)
    owner = _conversation(conversation_id)
    first = await service.preview_checkpoint(
        _Db(), owner, target_checkpoint_id=checkpoint.id, mode="code_only", workspace_root=str(workspace)
    )
    result = await service.execute_preview(_Db(), owner, uuid.UUID(first["preview_id"]))
    before_preview = await service.preview_operation_before(
        _Db(), owner, uuid.UUID(result["operation_id"]), str(workspace)
    )

    with pytest.raises(AppError) as exc:
        await service.execute_preview(_Db(), _conversation(uuid.uuid4()), uuid.UUID(before_preview["preview_id"]))

    assert exc.value.code == 40935


def _cursor_for_test(conversation: Conversation) -> tuple[object, ...]:
    return (
        conversation.active_message_head_id,
        conversation.active_graph_checkpoint_id,
        conversation.active_code_node_id,
        conversation.history_revision,
    )
