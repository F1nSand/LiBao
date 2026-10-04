from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.core.bootstrap import rebuild_legacy_bm25_if_needed
from app.services.kb import KbService
from app.services.kb_generation import KbGenerationService
from app.services.kb_migration import MigrationReport
from app.services.kb_recovery import RecoveryReport, kb_maintenance_loop, reconcile_kb_index
from app.storage.file.store import get_store
from app.storage.models.kb import EMBED_DIM, KbChunk
from app.storage.models.user import User
from app.storage.repositories.bm25 import BM25Index
from app.storage.repositories.kb import KbRepository


class FakeEmbedder:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * EMBED_DIM for _ in texts]


async def _indexed_document(content: str = "unique_recovery_term " + "body " * 180):
    repo = KbRepository()
    collection = await repo.create_collection(uuid.UUID(int=0), f"recovery-{uuid.uuid4().hex[:8]}", 512, 64)
    document = await repo.create_document(
        collection_id=collection.id,
        org_id=uuid.UUID(int=0),
        filename="recovery.txt",
        content_type="text/plain",
        size_bytes=len(content.encode()),
        content=content,
    )
    result = await KbGenerationService(repo=repo).build(document.id, embedder=FakeEmbedder())
    user = User(
        username=f"recovery-{uuid.uuid4().hex[:8]}",
        password_hash="hashed",
        name="Recovery Test",
        role="admin",
        org_id=uuid.UUID(int=0),
    )
    return repo, document, result, user


@pytest.mark.asyncio
async def test_archive_revokes_visibility_before_lance_cleanup_failure(monkeypatch):
    repo, document, result, user = await _indexed_document()
    manifest = await repo._load_index(document.collection_id)
    active_records = manifest["chunks"][str(document.id)][result.generation]
    repo.store.bm25 = BM25Index()
    repo.store.bm25.rebuild(
        [(row["chunk_id"], row["content"], str(document.collection_id)) for row in active_records]
    )

    async def fail_delete(document_id: uuid.UUID) -> None:
        raise RuntimeError("simulated Lance deletion failure")

    monkeypatch.setattr(repo.lance, "delete_document", fail_delete)
    service = KbService()
    async with get_store().session() as session:
        await service.archive_document(session, user, document.id, "archived")

    persisted = await repo.get_document(uuid.UUID(int=0), document.id)
    manifest = await repo._load_index(document.collection_id)
    assert persisted.status == "archived"
    assert persisted.active_generation is None
    assert persisted.index_state == "cleanup_pending"
    assert (await repo.lance.fts_search("unique_recovery_term", [document.collection_id], 10))
    hits = await repo.hybrid_search(
        uuid.UUID(int=0), [document.collection_id], "unique_recovery_term", hybrid={"semantic": 0, "bm25": 1}
    )
    assert hits == []
    assert result.generation in manifest["chunks"][str(document.id)]


@pytest.mark.asyncio
async def test_successful_archive_clears_chunk_metadata_and_count():
    repo, document, _result, user = await _indexed_document()

    async with get_store().session() as session:
        await KbService().archive_document(session, user, document.id, "archived")

    persisted = await repo.get_document(uuid.UUID(int=0), document.id)
    manifest = await repo.manifests.load(document.collection_id)
    assert persisted.status == "archived"
    assert persisted.chunk_count == 0
    assert str(document.id) not in manifest["chunks"]


@pytest.mark.asyncio
async def test_delete_revokes_visibility_before_lance_cleanup_failure(monkeypatch):
    repo, document, result, user = await _indexed_document()
    manifest = await repo._load_index(document.collection_id)
    records = manifest["chunks"][str(document.id)][result.generation]
    repo.store.bm25 = BM25Index()
    repo.store.bm25.rebuild(
        [(row["chunk_id"], row["content"], str(document.collection_id)) for row in records]
    )

    async def fail_delete(document_id: uuid.UUID) -> None:
        raise RuntimeError("simulated Lance deletion failure")

    monkeypatch.setattr(repo.lance, "delete_document", fail_delete)
    async with get_store().session() as session:
        await KbService().delete_document(session, user, document.id)

    assert await repo.get_document(uuid.UUID(int=0), document.id) is None
    manifest = await repo.manifests.load(document.collection_id)
    persisted = manifest["documents"][str(document.id)]
    assert persisted["deleted_at"]
    assert persisted["active_generation"] is None
    assert persisted["index_state"] == "cleanup_pending"
    hits = await repo.hybrid_search(
        uuid.UUID(int=0), [document.collection_id], "unique_recovery_term", hybrid={"semantic": 0, "bm25": 1}
    )
    assert hits == []


@pytest.mark.asyncio
async def test_recovery_removes_orphan_build_generation_and_is_idempotent():
    repo, document, _result, _user = await _indexed_document("orphan base body " * 30)
    orphan_generation = "gen-orphan"
    orphan = KbChunk(
        document_id=document.id,
        collection_id=document.collection_id,
        org_id=document.org_id,
        chunk_index=0,
        content="orphan row",
        generation=orphan_generation,
        embedding=[0.02] * EMBED_DIM,
    )
    await repo.lance.write_generation([orphan], active=False)

    def set_building(manifest):
        doc_state = manifest["documents"][str(document.id)]
        doc_state["building_generation"] = orphan_generation
        doc_state["index_state"] = "building"
        doc_state["status"] = "indexing"
        manifest["chunks"][str(document.id)][orphan_generation] = [
            {"chunk_id": str(orphan.id), "content": orphan.content, "generation": orphan_generation}
        ]

    await repo.update_manifest(document.collection_id, set_building, version=2)

    first = await reconcile_kb_index()
    second = await reconcile_kb_index()

    manifest = await repo.manifests.load(document.collection_id)
    doc_state = manifest["documents"][str(document.id)]
    assert first.repaired == 1
    assert second.repaired == 0
    assert doc_state["building_generation"] is None
    assert doc_state["status"] == "indexed"
    assert orphan_generation not in manifest["chunks"][str(document.id)]
    assert (await repo.lance.validate_generation(document.id, orphan_generation, 0)).row_count == 0


@pytest.mark.asyncio
async def test_recovery_marks_failed_orphan_cleanup_pending_and_retries(monkeypatch):
    repo, document, active, _user = await _indexed_document("orphan cleanup base " * 30)
    orphan_generation = "gen-orphan-retry"
    orphan = KbChunk(
        document_id=document.id,
        collection_id=document.collection_id,
        org_id=document.org_id,
        chunk_index=0,
        content="orphan row",
        generation=orphan_generation,
        embedding=[0.02] * EMBED_DIM,
    )
    await repo.lance.write_generation([orphan], active=False)

    def set_building(manifest):
        doc_state = manifest["documents"][str(document.id)]
        doc_state["building_generation"] = orphan_generation
        doc_state["index_state"] = "building"
        doc_state["status"] = "indexing"
        manifest["chunks"][str(document.id)][orphan_generation] = [
            {"chunk_id": str(orphan.id), "content": orphan.content, "generation": orphan_generation}
        ]

    await repo.update_manifest(document.collection_id, set_building, version=2)
    original_delete = repo.lance.delete_generation

    async def fail_once(document_id: uuid.UUID, generation: str) -> None:
        if generation == orphan_generation:
            raise RuntimeError("temporary orphan cleanup failure")
        await original_delete(document_id, generation)

    monkeypatch.setattr(repo.lance, "delete_generation", fail_once)
    first = await reconcile_kb_index()
    pending = await repo.manifests.load(document.collection_id)
    pending_doc = pending["documents"][str(document.id)]
    assert first.cleanup_pending == 1
    assert pending_doc["status"] == "indexed"
    assert pending_doc["index_state"] == "cleanup_pending"
    assert pending_doc["building_generation"] == orphan_generation
    assert pending_doc["active_generation"] == active.generation

    monkeypatch.setattr(repo.lance, "delete_generation", original_delete)
    second = await reconcile_kb_index()
    repaired = await repo.manifests.load(document.collection_id)
    assert second.repaired == 1
    assert repaired["documents"][str(document.id)]["index_state"] == "ready"
    assert repaired["documents"][str(document.id)]["building_generation"] is None


@pytest.mark.asyncio
async def test_recovery_retries_pending_old_generation_cleanup(monkeypatch):
    repo, document, old, _user = await _indexed_document()
    await repo.update_manifest(
        document.collection_id,
        lambda manifest: manifest["documents"][str(document.id)].update(
            status="uploaded", index_state="queued"
        ),
        version=2,
    )
    original_delete = repo.lance.delete_generation

    async def fail_old(document_id: uuid.UUID, generation: str) -> None:
        if generation == old.generation:
            raise RuntimeError("temporary cleanup failure")
        await original_delete(document_id, generation)

    monkeypatch.setattr(repo.lance, "delete_generation", fail_old)
    newer = await KbGenerationService(repo=repo).build(document.id, embedder=FakeEmbedder())
    monkeypatch.setattr(repo.lance, "delete_generation", original_delete)

    report = await reconcile_kb_index()
    manifest = await repo.manifests.load(document.collection_id)

    assert report.repaired == 1
    assert manifest["documents"][str(document.id)]["active_generation"] == newer.generation
    assert manifest["documents"][str(document.id)]["index_state"] == "ready"
    assert set(manifest["chunks"][str(document.id)]) == {newer.generation}
    assert (await repo.lance.validate_generation(document.id, old.generation, 0)).row_count == 0


@pytest.mark.asyncio
async def test_recovery_marks_missing_active_rows_repair_required_without_fabricating():
    repo, document, active, _user = await _indexed_document()
    await repo.lance.delete_generation(document.id, active.generation)

    report = await reconcile_kb_index()
    manifest = await repo.manifests.load(document.collection_id)

    assert report.repair_required == 1
    assert manifest["documents"][str(document.id)]["index_state"] == "repair_required"
    assert manifest["chunks"][str(document.id)][active.generation]
    assert (await repo.lance.validate_generation(document.id, active.generation, active.chunk_count)).row_count == 0


@pytest.mark.asyncio
async def test_healthy_v2_recovery_does_not_recreate_fts_index(monkeypatch):
    repo, document, active, _user = await _indexed_document()

    def fail_if_rebuilt(tokenizer: str) -> None:
        raise AssertionError(f"unexpected FTS initialization with tokenizer={tokenizer}")

    monkeypatch.setattr(repo.lance, "_ensure_ready", fail_if_rebuilt)

    report = await reconcile_kb_index()
    manifest = await repo.manifests.load(document.collection_id)

    assert report.errors == ()
    assert report.repair_required == 0
    assert manifest["documents"][str(document.id)]["active_generation"] == active.generation


@pytest.mark.asyncio
async def test_broken_collection_does_not_block_recovery_of_another():
    repo, document, _active, _user = await _indexed_document()
    broken_collection = await repo.create_collection(uuid.UUID(int=0), f"broken-{uuid.uuid4().hex[:8]}", 512, 64)
    broken_path = repo._index_path(broken_collection.id)
    broken_path.write_text("{broken", encoding="utf-8")

    report = await reconcile_kb_index()

    manifest = await repo.manifests.load(document.collection_id)
    assert report.scanned >= 1
    assert report.errors
    assert manifest["documents"][str(document.id)]["active_generation"] == _active.generation


@pytest.mark.asyncio
async def test_lifespan_runs_recovery_and_cancels_kb_maintenance(monkeypatch):
    import app.api.lifespan as lifespan_module

    settings = SimpleNamespace(
        agent_data_dir=".agent-test",
        checkpoint_retention_days=7,
        kb_recovery_enabled=True,
        kb_maintenance_interval_s=3600,
        kb_optimize_min_mutations=500,
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()
    recovery_calls = []

    class CheckpointService:
        async def recover_open_checkpoints(self):
            return 0

        async def recover_incomplete_operations(self):
            return 0

    async def wait_for_cancel(settings):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def no_op(*args, **kwargs):
        return None

    async def fake_init_runtime(settings):
        return SimpleNamespace(
            store=object(),
            kb_index_mode="v2",
            kb_migration=MigrationReport(0, 0, 0, 0, 0, True),
        )

    async def no_task_recovery(*args, **kwargs):
        return {"scanned": 0}

    async def recovered():
        recovery_calls.append(True)
        return RecoveryReport(0, 0, 0, 0, ())

    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    monkeypatch.setattr(lifespan_module, "init_runtime", fake_init_runtime)
    monkeypatch.setattr(lifespan_module, "build_checkpointer", lambda settings: object())
    monkeypatch.setattr(lifespan_module, "build_graph", lambda saver: object())
    monkeypatch.setattr(lifespan_module, "get_checkpoint_service", lambda *args: CheckpointService())
    monkeypatch.setattr(lifespan_module, "reconcile_orphaned_tasks", no_task_recovery)
    monkeypatch.setattr(lifespan_module, "reconcile_kb_index", recovered)
    monkeypatch.setattr(lifespan_module, "kb_maintenance_loop", wait_for_cancel)
    monkeypatch.setattr(lifespan_module, "session_cache_loop", wait_for_cancel)
    monkeypatch.setattr(lifespan_module, "cleanup_runtime", no_op)

    app = FastAPI()
    async with lifespan_module.lifespan(app):
        await asyncio.wait_for(started.wait(), timeout=2)

    assert recovery_calls == [True]
    assert app.state.kb_index_mode == "v2"
    assert app.state.kb_migration.complete
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_maintenance_optimizes_at_mutation_threshold_and_cancels_cleanly(monkeypatch):
    import app.services.kb_recovery as recovery_module

    reconciled = asyncio.Event()
    optimized = asyncio.Event()

    class FakeLanceStore:
        mutation_count = 12

        async def optimize(self):
            optimized.set()
            self.mutation_count = 0

    lance_store = FakeLanceStore()
    monkeypatch.setattr(recovery_module, "get_store", lambda: SimpleNamespace(kb_lance_store=lance_store))

    async def fake_reconcile():
        reconciled.set()
        return RecoveryReport(0, 0, 0, 0, ())

    monkeypatch.setattr(recovery_module, "reconcile_kb_index", fake_reconcile)
    task = asyncio.create_task(
        kb_maintenance_loop(
            SimpleNamespace(kb_maintenance_interval_s=0, kb_optimize_min_mutations=10)
        )
    )
    await asyncio.wait_for(reconciled.wait(), timeout=2)
    await asyncio.wait_for(optimized.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert lance_store.mutation_count == 0


@pytest.mark.asyncio
async def test_bootstrap_skips_legacy_bm25_rebuild_when_only_v2_documents_exist(monkeypatch):
    class FakeRepository:
        async def has_legacy_active_documents(self):
            return False

    calls = []
    store = SimpleNamespace(bm25=SimpleNamespace(rebuild=lambda corpus: calls.append(corpus)))
    monkeypatch.setattr("app.storage.repositories.kb.KbRepository", FakeRepository)

    assert await rebuild_legacy_bm25_if_needed(store) is False
    assert calls == []


@pytest.mark.asyncio
async def test_bootstrap_rebuilds_legacy_bm25_only_for_v1_fallback(monkeypatch):
    class FakeRepository:
        async def has_legacy_active_documents(self):
            return True

        async def _bm25_corpus(self):
            return [("chunk", "legacy text", "collection")]

    calls = []
    store = SimpleNamespace(bm25=SimpleNamespace(rebuild=lambda corpus: calls.append(corpus)))
    monkeypatch.setattr("app.storage.repositories.kb.KbRepository", FakeRepository)

    assert await rebuild_legacy_bm25_if_needed(store) is True
    assert calls == [[("chunk", "legacy text", "collection")]]
