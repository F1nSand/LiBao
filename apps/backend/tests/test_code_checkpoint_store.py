from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.checkpoints.models import ConversationCursor, FileRestoreResult, FileVersionRef, RollbackOperation
from app.checkpoints.service import CheckpointService
from app.checkpoints.store import CodeCheckpointStore


@pytest.mark.asyncio
async def test_anchor_is_empty_and_persists(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store)
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()

    checkpoint = await service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=message_id,
        workspace_identity="workspace-a",
        anchor_message_head_id=message_id,
    )

    loaded = await store.read_checkpoint(conversation_id, checkpoint.id)
    assert loaded is not None
    assert loaded.user_message_id == message_id
    assert loaded.files == {}
    assert (tmp_path / ".agent" / "code-checkpoints" / str(conversation_id) / "index.json").is_file()


@pytest.mark.asyncio
async def test_create_checkpoint_is_idempotent(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store)
    conversation_id = uuid.uuid4()
    checkpoint = await service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity="workspace-a",
        anchor_message_head_id=uuid.uuid4(),
    )

    recreated = await asyncio.wait_for(store.create_checkpoint(checkpoint), timeout=1)

    assert recreated.to_dict() == checkpoint.to_dict()


@pytest.mark.asyncio
async def test_prepare_file_deduplicates_blob_and_keeps_first_before(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store)
    conversation_id = uuid.uuid4()
    checkpoint = await service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity="workspace-a",
        anchor_message_head_id=uuid.uuid4(),
    )

    first = await store.prepare_file(
        conversation_id,
        checkpoint.id,
        "src/a.bin",
        b"before",
        tool_call_id="call-1",
    )
    second = await store.prepare_file(
        conversation_id,
        checkpoint.id,
        "src/a.bin",
        b"different-current-content",
        tool_call_id="call-2",
    )

    assert first.before.blob_sha256 == second.before.blob_sha256
    assert second.tool_call_ids == ["call-1", "call-2"]
    blobs = list((tmp_path / ".agent" / "code-checkpoints" / str(conversation_id) / "blobs").rglob("*"))
    assert [p for p in blobs if p.is_file()]


@pytest.mark.asyncio
async def test_binary_blob_roundtrip_and_missing_file_ref(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store)
    conversation_id = uuid.uuid4()
    checkpoint = await service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity="workspace-a",
        anchor_message_head_id=uuid.uuid4(),
    )

    await store.prepare_file(conversation_id, checkpoint.id, "image.png", b"\x89PNG\x00\xff", tool_call_id="call")
    await store.prepare_missing_file(conversation_id, checkpoint.id, "new.txt", tool_call_id="call-new")
    loaded = await store.read_checkpoint(conversation_id, checkpoint.id)
    assert loaded is not None
    image = loaded.files["image.png"].before
    assert image.content_kind == "binary"
    assert await store.read_blob(conversation_id, image.blob_sha256) == b"\x89PNG\x00\xff"
    assert loaded.files["new.txt"].before == FileVersionRef(False, None, 0, "text")


@pytest.mark.asyncio
async def test_cleanup_expired_removes_only_old_sessions(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store, retention_days=30)
    old = uuid.uuid4()
    fresh = uuid.uuid4()
    for cid in (old, fresh):
        await service.create_anchor(
            conversation_id=cid,
            user_message_id=uuid.uuid4(),
            workspace_identity="workspace-a",
            anchor_message_head_id=uuid.uuid4(),
        )
    old_dir = store.session_dir(old)
    old_time = datetime.now(UTC) - timedelta(days=31)
    index_path = old_dir / "index.json"
    index = __import__("json").loads(index_path.read_text(encoding="utf-8"))
    index["last_active_at"] = old_time.isoformat()
    index_path.write_text(__import__("json").dumps(index), encoding="utf-8")
    assert await service.cleanup_expired(now=datetime.now(UTC)) == 1
    assert not old_dir.exists()
    assert store.session_dir(fresh).exists()


@pytest.mark.asyncio
async def test_operation_update_is_atomic_and_v2_round_trips(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    conversation_id = uuid.uuid4()
    operation = RollbackOperation(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        target_checkpoint_id=uuid.uuid4(),
        mode="both",
        before_cursor=ConversationCursor(None, None, None, 1, True, True),
        planned_after_cursor=ConversationCursor(None, None, None, 2, True, True),
        after_cursor=None,
        undo_files={},
        file_results=[],
        status="prepared",
        planned_files=[{"path": "a.txt", "action": "restore", "current_sha256": "abc"}],
    )
    await store.create_operation(operation)

    operation.status = "failed_partial"
    operation.applied_paths.append("a.txt")
    operation.error = {"code": "injected", "message": "write failed"}
    await store.update_operation(operation)
    loaded = await store.read_operation(conversation_id, operation.id)

    assert loaded is not None
    assert loaded.status == "failed_partial"
    assert loaded.applied_paths == ["a.txt"]
    assert loaded.planned_after_cursor is not None
    assert loaded.after_cursor is None
    assert loaded.error == {"code": "injected", "message": "write failed"}


@pytest.mark.asyncio
async def test_recover_incomplete_operations_marks_only_journals(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store)
    conversation_id = uuid.uuid4()
    operation = RollbackOperation(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        target_checkpoint_id=uuid.uuid4(),
        mode="code_only",
        before_cursor=ConversationCursor(None, None, None, 0),
        planned_after_cursor=ConversationCursor(None, None, None, 1),
        after_cursor=None,
        undo_files={},
        file_results=[FileRestoreResult("a.txt", "restored")],
        status="applying",
    )
    await store.create_operation(operation)

    assert await service.recover_incomplete_operations() == 1
    recovered = await store.read_operation(conversation_id, operation.id)
    assert recovered is not None
    assert recovered.status == "failed_partial"
    assert recovered.error and recovered.error["code"] == "incomplete_operation"


@pytest.mark.asyncio
async def test_recover_incomplete_operation_with_durable_after_cursor_is_completed(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store)
    conversation_id = uuid.uuid4()
    operation = RollbackOperation(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        target_checkpoint_id=uuid.uuid4(),
        mode="code_only",
        before_cursor=ConversationCursor(None, None, None, 0),
        planned_after_cursor=ConversationCursor(None, None, None, 1),
        after_cursor=ConversationCursor(None, None, None, 1),
        undo_files={},
        file_results=[FileRestoreResult("a.txt", "restored")],
        status="applying",
        planned_files=[{"path": "a.txt"}],
    )
    await store.create_operation(operation)

    assert await service.recover_incomplete_operations() == 1
    recovered = await store.read_operation(conversation_id, operation.id)
    assert recovered is not None
    assert recovered.status == "completed"
    assert recovered.error is None


def test_legacy_operation_reader_defaults_new_wal_fields():
    raw = {
        "id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "target_checkpoint_id": str(uuid.uuid4()),
        "mode": "code_only",
        "before_cursor": ConversationCursor(None, None, None, 1).to_dict(),
        "after_cursor": None,
        "undo_files": {},
        "file_results": [],
        "status": "completed",
        "created_at": datetime.now(UTC).isoformat(),
    }

    operation = RollbackOperation.from_dict(raw)

    assert operation.preview_id is None
    assert operation.planned_files == []
    assert operation.applied_paths == []
    assert operation.planned_after_cursor is None
    assert operation.error is None
    assert operation.after_cursor is None
