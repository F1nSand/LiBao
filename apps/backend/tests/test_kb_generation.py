from __future__ import annotations

import asyncio
import uuid

import pytest

from app.services.kb import KbService
from app.services.kb_generation import (
    DOCUMENT_INDEX_LOCKS,
    GenerationBuildError,
    KbGenerationService,
)
from app.storage.file.store import get_store
from app.storage.models.kb import EMBED_DIM, KbChunk
from app.storage.models.user import User
from app.storage.repositories.bm25 import BM25Index
from app.storage.repositories.kb import KbRepository
from app.storage.repositories.kb_lance import GenerationValidation


class FakeEmbedder:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.01 * (index + 1)] * 1024 for index, _ in enumerate(texts)]


class FailingEmbedder:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("simulated embedding failure")


async def _new_document(content: str = "needle " + "body " * 220):
    repo = KbRepository()
    collection = await repo.create_collection(uuid.UUID(int=0), f"generation-{uuid.uuid4().hex[:8]}", 512, 64)
    document = await repo.create_document(
        collection_id=collection.id,
        org_id=uuid.UUID(int=0),
        filename="generation.txt",
        content_type="text/plain",
        size_bytes=len(content.encode()),
        content=content,
    )
    return repo, document


async def _queue_reindex(repo: KbRepository, document_id: uuid.UUID) -> None:
    document = await repo.get_document(uuid.UUID(int=0), document_id)
    document.status = "uploaded"
    document.index_state = "queued"
    await repo.persist_document(document)


@pytest.mark.asyncio
async def test_build_and_reindex_activate_one_manifest_and_lance_generation():
    repo, document = await _new_document()
    service = KbGenerationService(repo=repo)

    first = await service.build(document.id, embedder=FakeEmbedder())
    await _queue_reindex(repo, document.id)
    second = await service.build(document.id, embedder=FakeEmbedder())

    manifest = await repo._load_index(document.collection_id)
    persisted = manifest["documents"][str(document.id)]
    generations = manifest["chunks"][str(document.id)]
    assert first.generation != second.generation
    assert manifest["version"] == 2
    assert first.replaced_generation is None
    assert second.replaced_generation == first.generation
    assert persisted["active_generation"] == second.generation
    assert persisted["building_generation"] is None
    assert persisted["status"] == "indexed"
    assert set(generations) == {second.generation}
    validation = await repo.lance.validate_generation(document.id, second.generation, second.chunk_count)
    assert validation.row_count_matches and validation.vector_dimensions_valid
    assert (await repo.lance.validate_generation(document.id, first.generation, 0)).row_count == 0
    hits = await repo.lance.fts_search("needle", [document.collection_id], limit=20)
    assert hits and {hit.generation for hit in hits} == {second.generation}


@pytest.mark.asyncio
async def test_reindex_keeps_legacy_generation_until_migration():
    repo, document = await _new_document()
    repo.store.bm25 = BM25Index()
    document.status = "indexed"
    document.chunk_count = 1
    await repo.persist_document(document)
    legacy_chunk = KbChunk(
        document_id=document.id,
        collection_id=document.collection_id,
        org_id=document.org_id,
        chunk_index=0,
        content="legacy needle passage",
        embedding=[0.01] * EMBED_DIM,
    )
    await repo.insert_chunks([legacy_chunk])
    await _queue_reindex(repo, document.id)

    result = await KbGenerationService(repo=repo).build(document.id, embedder=FakeEmbedder())

    manifest = await repo._load_index(document.collection_id)
    generations = manifest["chunks"][str(document.id)]
    assert manifest["version"] == 2
    assert generations["legacy-v1"][0]["chunk_id"] == str(legacy_chunk.id)
    assert result.generation in generations
    assert manifest["documents"][str(document.id)]["active_generation"] == result.generation


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["split", "embedding", "lance_write", "validation", "activation"])
async def test_pre_activation_failures_keep_old_generation_active(failure_point, monkeypatch):
    repo, document = await _new_document()
    service = KbGenerationService(repo=repo)
    old = await service.build(document.id, embedder=FakeEmbedder())
    await _queue_reindex(repo, document.id)

    failed_generations: list[str] = []
    delete_generation = repo.lance.delete_generation
    validate_generation = repo.lance.validate_generation

    async def capture_cleanup(document_id: uuid.UUID, generation: str) -> None:
        failed_generations.append(generation)
        await delete_generation(document_id, generation)

    monkeypatch.setattr(repo.lance, "delete_generation", capture_cleanup)
    embedder = FakeEmbedder()
    if failure_point == "split":
        def fail_split(*args, **kwargs):
            raise RuntimeError("simulated split failure")

        service.chunker = fail_split
    elif failure_point == "embedding":
        embedder = FailingEmbedder()
    elif failure_point == "lance_write":
        async def fail_write(*args, **kwargs):
            raise RuntimeError("simulated Lance write failure")

        monkeypatch.setattr(repo.lance, "write_generation", fail_write)
    elif failure_point == "validation":
        async def fail_validation(*args, **kwargs):
            return GenerationValidation(0, False, 0, False, 1)

        monkeypatch.setattr(repo.lance, "validate_generation", fail_validation)
    elif failure_point == "activation":
        async def fail_activation(*args, **kwargs):
            raise RuntimeError("simulated manifest activation failure")

        monkeypatch.setattr(service, "activate", fail_activation)

    with pytest.raises(GenerationBuildError):
        await service.build(document.id, embedder=embedder)

    persisted = await repo.get_document(uuid.UUID(int=0), document.id)
    manifest = await repo._load_index(document.collection_id)
    assert persisted.status == "indexed"
    assert persisted.active_generation == old.generation
    assert persisted.building_generation is None
    assert persisted.last_index_error
    assert set(manifest["chunks"][str(document.id)]) == {old.generation}
    assert failed_generations and old.generation not in failed_generations
    assert (await validate_generation(document.id, old.generation, old.chunk_count)).row_count_matches
    hits = await repo.lance.fts_search("needle", [document.collection_id], limit=20)
    assert hits and {hit.generation for hit in hits} == {old.generation}


@pytest.mark.asyncio
async def test_old_generation_cleanup_failure_keeps_new_generation_and_marks_pending(monkeypatch):
    repo, document = await _new_document()
    service = KbGenerationService(repo=repo)
    old = await service.build(document.id, embedder=FakeEmbedder())
    await _queue_reindex(repo, document.id)
    delete_generation = repo.lance.delete_generation

    async def fail_old_cleanup(document_id: uuid.UUID, generation: str) -> None:
        if generation == old.generation:
            raise RuntimeError("simulated old-generation cleanup failure")
        await delete_generation(document_id, generation)

    monkeypatch.setattr(repo.lance, "delete_generation", fail_old_cleanup)
    result = await service.build(document.id, embedder=FakeEmbedder())

    persisted = await repo.get_document(uuid.UUID(int=0), document.id)
    manifest = await repo._load_index(document.collection_id)
    assert result.generation != old.generation
    assert persisted.active_generation == result.generation
    assert persisted.index_state == "cleanup_pending"
    assert set(manifest["chunks"][str(document.id)]) == {old.generation, result.generation}
    assert (await repo.lance.validate_generation(document.id, old.generation, old.chunk_count)).row_count_matches
    hits = await repo.lance.fts_search("needle", [document.collection_id], limit=20)
    assert hits and {hit.generation for hit in hits} == {result.generation}


@pytest.mark.asyncio
async def test_cancelled_reindex_clears_build_marker_and_preserves_old_generation():
    repo, document = await _new_document()
    service = KbGenerationService(repo=repo)
    old = await service.build(document.id, embedder=FakeEmbedder())
    await _queue_reindex(repo, document.id)
    started = asyncio.Event()

    class PausedEmbedder:
        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(service.build(document.id, embedder=PausedEmbedder()))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    persisted = await repo.get_document(uuid.UUID(int=0), document.id)
    assert persisted.status == "indexed"
    assert persisted.active_generation == old.generation
    assert persisted.building_generation is None
    assert (await repo.lance.validate_generation(document.id, old.generation, old.chunk_count)).row_count_matches


@pytest.mark.asyncio
async def test_concurrent_builds_for_one_document_are_serialized():
    repo, document = await _new_document()
    service = KbGenerationService(repo=repo)
    entered = 0
    max_entered = 0

    class TrackingEmbedder:
        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            nonlocal entered, max_entered
            entered += 1
            max_entered = max(max_entered, entered)
            await asyncio.sleep(0.02)
            entered -= 1
            return [[0.01] * 1024 for _ in texts]

    results = await asyncio.gather(
        service.build(document.id, embedder=TrackingEmbedder()),
        service.build(document.id, embedder=TrackingEmbedder()),
    )

    assert max_entered == 1
    assert results[0].generation == results[1].generation
    manifest = await repo._load_index(document.collection_id)
    assert set(manifest["chunks"][str(document.id)]) == {results[0].generation}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_name", ["reindex", "archive", "delete"])
async def test_lifecycle_operations_share_generation_document_lock(operation_name, monkeypatch):
    repo, document = await _new_document()
    user = User(
        username=f"lock-{uuid.uuid4().hex[:8]}",
        password_hash="hashed",
        name="Lock Test",
        role="admin",
        org_id=uuid.UUID(int=0),
    )
    service = KbService()
    monkeypatch.setattr("app.services.kb._spawn_pipeline", lambda document_id: None)

    async def run_operation():
        async with get_store().session() as session:
            if operation_name == "reindex":
                await service.reindex_document(session, user, document.id)
            elif operation_name == "archive":
                await service.archive_document(session, user, document.id, "archived")
            else:
                await service.delete_document(session, user, document.id)

    async with DOCUMENT_INDEX_LOCKS.acquire(document.id):
        task = asyncio.create_task(run_operation())
        await asyncio.sleep(0.01)
        assert not task.done()
    await asyncio.wait_for(task, timeout=2)

    persisted = await repo.get_document(uuid.UUID(int=0), document.id)
    if operation_name == "reindex":
        assert persisted.status == "uploaded"
        assert persisted.index_state == "queued"
    elif operation_name == "archive":
        assert persisted.status == "archived"
    else:
        assert persisted is None


@pytest.mark.asyncio
async def test_duplicate_reindex_requests_are_serialized_and_second_is_rejected(monkeypatch):
    _, document = await _new_document()
    user = User(
        username=f"reindex-{uuid.uuid4().hex[:8]}",
        password_hash="hashed",
        name="Reindex Test",
        role="admin",
        org_id=uuid.UUID(int=0),
    )
    service = KbService()
    monkeypatch.setattr("app.services.kb._spawn_pipeline", lambda document_id: None)

    async def request_reindex():
        async with get_store().session() as session:
            await service.reindex_document(session, user, document.id)

    results = await asyncio.gather(request_reindex(), request_reindex(), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert "正在处理中" in str(errors[0])
