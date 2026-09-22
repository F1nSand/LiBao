"""Generation-safe KB indexing with manifest activation as the visibility boundary."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.core.embeddings import EmbeddingService
from app.services.chunker import chunk_text
from app.storage.kb.manifest import LEGACY_GENERATION
from app.storage.models.kb import EMBED_DIM, KbChunk, KbDocument
from app.storage.repositories.kb import KbRepository


class GenerationBuildError(RuntimeError):
    """An indexing failure whose document state has already been persisted."""


@dataclass(frozen=True, slots=True)
class IndexBuildResult:
    document_id: uuid.UUID
    generation: str
    chunk_count: int
    replaced_generation: str | None


class DocumentIndexLocks:
    """Per-document serialization shared by indexing and lifecycle operations."""

    _locks: dict[tuple[asyncio.AbstractEventLoop, str], asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(self, document_id: uuid.UUID) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        key = (loop, str(document_id))
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            yield


DOCUMENT_INDEX_LOCKS = DocumentIndexLocks()


class KbGenerationService:
    def __init__(
        self,
        repo: KbRepository | None = None,
        *,
        chunker: Callable[[str, int, int], list[str]] = chunk_text,
        locks: DocumentIndexLocks = DOCUMENT_INDEX_LOCKS,
    ) -> None:
        self.repo = repo or KbRepository()
        self.chunker = chunker
        self.locks = locks

    async def build(
        self, document_id: uuid.UUID, *, embedder: EmbeddingService | None = None
    ) -> IndexBuildResult:
        async with self.locks.acquire(document_id):
            return await self._build_locked(document_id, embedder=embedder)

    async def _build_locked(
        self, document_id: uuid.UUID, *, embedder: EmbeddingService | None
    ) -> IndexBuildResult:
        doc = await self.repo.get_document(uuid.UUID(int=0), document_id)
        if doc is None:
            raise GenerationBuildError("文档不存在")
        if doc.deleted_at is not None or doc.status == "archived":
            raise GenerationBuildError("文档已归档或删除，不能索引")
        if doc.status == "indexed" and doc.active_generation and doc.building_generation is None:
            return IndexBuildResult(doc.id, doc.active_generation, doc.chunk_count, None)
        if doc.status not in {"uploaded", "failed", "chunking", "indexing"}:
            raise GenerationBuildError(f"文档状态不允许索引: {doc.status}")

        generation = f"gen-{uuid.uuid4().hex}"
        old_generation = doc.active_generation
        rows: list[KbChunk] = []
        activated = False
        failure_stage = "索引初始化失败"
        try:
            await self._update_document(
                doc,
                {
                    "building_generation": generation,
                    "index_state": "building",
                    "status": "chunking",
                    "last_index_error": None,
                },
                version=2,
            )
            collection = await self.repo.get_collection(uuid.UUID(int=0), doc.collection_id)
            if collection is None:
                raise RuntimeError("集合不存在")

            failure_stage = "分块失败"
            texts = self.chunker(doc.content, collection.chunk_size, collection.chunk_overlap)
            if not texts:
                raise RuntimeError("文档内容为空，无法分块")
            max_chunks = get_settings().kb_max_chunks
            if len(texts) > max_chunks:
                raise RuntimeError(f"分块数 {len(texts)} 超过上限 {max_chunks}")

            await self._update_document(doc, {"status": "indexing"}, version=2)
            failure_stage = "向量化失败"
            embedder = embedder or EmbeddingService()
            vectors = await embedder.embed_documents(texts)
            if len(vectors) != len(texts):
                raise RuntimeError("向量化返回数量不符")

            rows = [
                KbChunk(
                    document_id=doc.id,
                    collection_id=doc.collection_id,
                    org_id=doc.org_id,
                    chunk_index=index,
                    content=text,
                    embedding=vectors[index],
                    embedding_model=collection.embedding_model,
                    generation=generation,
                    retrieval_text=text,
                    start_offset=0,
                    end_offset=len(text),
                    token_count=0,
                    chunking_strategy=collection.chunking_strategy,
                )
                for index, text in enumerate(texts)
            ]
            failure_stage = "索引落库失败"
            await self._complete_before_cancel(self.repo.lance.write_generation(rows, active=False))
            failure_stage = "generation 校验失败"
            validation = await self._complete_before_cancel(
                self.repo.lance.validate_generation(doc.id, generation, len(rows))
            )
            if (
                not validation.row_count_matches
                or validation.unique_chunk_count != len(rows)
                or not validation.vector_dimensions_valid
                or validation.empty_text_count > 0
            ):
                raise RuntimeError(
                    "新 generation 校验失败: "
                    f"rows={validation.row_count}/{len(rows)}, "
                    f"unique={validation.unique_chunk_count}, "
                    f"vectors_valid={validation.vector_dimensions_valid}, "
                    f"empty_text={validation.empty_text_count}"
                )
            failure_stage = "generation 激活失败"
            await self._complete_before_cancel(
                self.repo.lance.set_generation_active(doc.id, generation, True)
            )
            replaced_generation = await self.activate(doc, generation, rows)
            activated = True
            result = IndexBuildResult(doc.id, generation, len(rows), replaced_generation)

            if replaced_generation and replaced_generation != LEGACY_GENERATION:
                try:
                    await self.cleanup_generation(doc.id, replaced_generation)
                except asyncio.CancelledError:
                    await self._mark_cleanup_pending(doc.id, generation, "旧 generation 清理已取消")
                    raise
                except Exception as exc:  # noqa: BLE001  新 generation 已激活，不回滚
                    await self._mark_cleanup_pending(doc.id, generation, str(exc))
            return result
        except asyncio.CancelledError:
            if activated:
                await self._mark_cleanup_pending(document_id, generation, "generation 激活后任务取消")
            else:
                await self._rollback(document_id, generation, rows, "索引任务已取消")
            raise
        except Exception as exc:  # noqa: BLE001  错误持久化后由适配层吞并
            if activated:
                await self._mark_cleanup_pending(document_id, generation, str(exc))
                return IndexBuildResult(doc.id, generation, len(rows), old_generation)
            message = f"{failure_stage}: {exc}"[:500]
            await self._rollback(document_id, generation, rows, message)
            raise GenerationBuildError(message) from exc

    async def activate(
        self, document: KbDocument, generation: str, chunks: Sequence[KbChunk]
    ) -> str | None:
        old_generation = document.active_generation
        chunk_records = [self._chunk_manifest_record(chunk) for chunk in chunks]

        def activate_manifest(manifest: dict[str, Any]) -> None:
            document_id = str(document.id)
            doc_state = manifest["documents"][document_id]
            doc_state.update(
                {
                    "active_generation": generation,
                    "building_generation": None,
                    "index_state": "ready",
                    "status": "indexed",
                    "chunk_count": len(chunk_records),
                    "embedding_dimension": EMBED_DIM,
                    "retrieval_schema_version": 2,
                    "last_indexed_at": datetime.now(UTC).isoformat(),
                    "last_index_error": None,
                    "error": None,
                }
            )
            manifest["chunks"].setdefault(document_id, {})[generation] = chunk_records

        await self.repo.update_manifest(document.collection_id, activate_manifest, version=2)
        document.active_generation = generation
        document.building_generation = None
        document.index_state = "ready"
        document.status = "indexed"
        document.chunk_count = len(chunk_records)
        document.embedding_dimension = EMBED_DIM
        document.retrieval_schema_version = 2
        document.last_indexed_at = datetime.now(UTC)
        document.last_index_error = None
        document.error = None
        return old_generation

    async def cleanup_generation(self, document_id: uuid.UUID, generation: str) -> None:
        if generation == LEGACY_GENERATION:
            return  # Keep legacy data intact until the v1→v2 migration completes.
        document = await self.repo.get_document(uuid.UUID(int=0), document_id)
        if document is None:
            raise RuntimeError("清理 generation 时文档不存在")
        await self._complete_before_cancel(
            self.repo.lance.set_generation_active(document_id, generation, False)
        )
        await self._complete_before_cancel(self.repo.lance.delete_generation(document_id, generation))

        def remove_manifest_generation(manifest: dict[str, Any]) -> None:
            manifest["chunks"].get(str(document_id), {}).pop(generation, None)

        await self.repo.update_manifest(document.collection_id, remove_manifest_generation, version=2)

    async def _rollback(
        self,
        document_id: uuid.UUID,
        generation: str,
        rows: Sequence[KbChunk],
        message: str,
    ) -> None:
        cleanup_error: Exception | None = None
        try:
            await self._complete_before_cancel(self.repo.lance.delete_generation(document_id, generation))
        except Exception as exc:  # noqa: BLE001  后台恢复可重试未激活代
            cleanup_error = exc

        document = await self.repo.get_document(uuid.UUID(int=0), document_id)
        if document is None:
            return
        has_active = bool(document.active_generation)
        pending = cleanup_error is not None
        records = [self._chunk_manifest_record(chunk) for chunk in rows]

        def restore_manifest(manifest: dict[str, Any]) -> None:
            doc_state = manifest["documents"][str(document_id)]
            doc_state.update(
                {
                    "building_generation": None,
                    "index_state": "cleanup_pending" if pending else ("ready" if has_active else "failed"),
                    "status": "indexed" if has_active else "failed",
                    "last_index_error": message,
                }
            )
            generations = manifest["chunks"].setdefault(str(document_id), {})
            if pending:
                generations[generation] = records
            else:
                generations.pop(generation, None)
            if not has_active:
                doc_state["error"] = message

        await self.repo.update_manifest(document.collection_id, restore_manifest, version=2)
        document.building_generation = None
        document.index_state = "cleanup_pending" if pending else ("ready" if has_active else "failed")
        document.status = "indexed" if has_active else "failed"
        document.last_index_error = message
        if not has_active:
            document.error = message

    async def _mark_cleanup_pending(self, document_id: uuid.UUID, generation: str, message: str) -> None:
        document = await self.repo.get_document(uuid.UUID(int=0), document_id)
        if document is None:
            return

        def mark_pending(manifest: dict[str, Any]) -> None:
            doc_state = manifest["documents"][str(document_id)]
            doc_state["index_state"] = "cleanup_pending"
            doc_state["last_index_error"] = message[:500]

        await self.repo.update_manifest(document.collection_id, mark_pending, version=2)
        document.index_state = "cleanup_pending"
        document.last_index_error = message[:500]

    async def _update_document(
        self, document: KbDocument, fields: dict[str, Any], *, version: int
    ) -> None:
        def update_manifest(manifest: dict[str, Any]) -> None:
            manifest["documents"][str(document.id)].update(fields)

        await self.repo.update_manifest(document.collection_id, update_manifest, version=version)
        for field, value in fields.items():
            setattr(document, field, value)

    @staticmethod
    def _chunk_manifest_record(chunk: KbChunk) -> dict[str, Any]:
        return {
            "chunk_id": str(chunk.id),
            "document_id": str(chunk.document_id),
            "collection_id": str(chunk.collection_id),
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "generation": chunk.generation,
            "retrieval_text": chunk.retrieval_text or chunk.content,
            "section_path": list(chunk.section_path),
            "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset,
            "token_count": chunk.token_count,
            "chunking_strategy": chunk.chunking_strategy,
        }

    @staticmethod
    async def _complete_before_cancel(awaitable):
        task = asyncio.create_task(awaitable)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except Exception:  # noqa: BLE001  cancellation remains the externally visible outcome
                pass
            raise
