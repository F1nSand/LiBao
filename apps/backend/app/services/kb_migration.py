"""Resumable side-by-side migration from v1 chunks to persistent Lance FTS."""

from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.services.kb_generation import DOCUMENT_INDEX_LOCKS, KbGenerationService
from app.storage.kb.manifest import LEGACY_GENERATION
from app.storage.models.kb import EMBED_DIM, KbChunk, KbDocument
from app.storage.repositories.kb import KbRepository, _collection_dirs

MigrationStatus = Literal["migrated", "skipped", "reindex_required", "failed"]


@dataclass(frozen=True, slots=True)
class DocumentMigrationResult:
    document_id: uuid.UUID
    status: MigrationStatus
    chunk_count: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationReport:
    total: int
    migrated: int
    skipped: int
    reindex_required: int
    failed: int
    complete: bool


class KbV2Migrator:
    def __init__(self, repo: KbRepository | None = None) -> None:
        self.repo = repo or KbRepository()
        self.ledger_path = Path(self.repo.store.kb_root) / "migration-v2.json"
        self._ledger_lock = asyncio.Lock()

    async def migrate_document(
        self, collection_id: uuid.UUID, document_id: uuid.UUID
    ) -> DocumentMigrationResult:
        async with DOCUMENT_INDEX_LOCKS.acquire(document_id):
            try:
                return await self._migrate_document_locked(collection_id, document_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001  expose a resumable per-document failure
                return DocumentMigrationResult(document_id, "failed", 0, type(exc).__name__)

    async def _migrate_document_locked(
        self,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        manifest: dict[str, Any] | None = None,
        document_data: dict[str, Any] | None = None,
    ) -> DocumentMigrationResult:
        manifest = manifest if manifest is not None else await self.repo.manifests.load(collection_id)
        document_data = (
            document_data
            if document_data is not None
            else manifest["documents"].get(str(document_id))
        )
        if document_data is None or document_data.get("deleted_at"):
            return DocumentMigrationResult(document_id, "skipped", 0, "document is deleted")
        stored_collection_id = document_data.get("collection_id")
        if stored_collection_id and uuid.UUID(str(stored_collection_id)) != collection_id:
            return DocumentMigrationResult(document_id, "failed", 0, "collection id does not match document")
        document = KbDocument.from_dict(document_data)
        document.collection_id = collection_id
        if document.deleted_at or document.status != "indexed":
            return DocumentMigrationResult(document_id, "skipped", 0, "document is not active and indexed")
        if document.active_generation != LEGACY_GENERATION:
            return DocumentMigrationResult(document_id, "skipped", document.chunk_count)

        raw_generations = manifest["chunks"].get(str(document_id), {})
        legacy_chunks = (
            raw_generations
            if isinstance(raw_generations, list)
            else raw_generations.get(LEGACY_GENERATION, [])
        )
        if not legacy_chunks:
            return DocumentMigrationResult(document_id, "reindex_required", 0, "legacy chunk records are missing")

        legacy_rows = await self.repo.legacy_vector_rows(document_id)
        vectors: dict[str, list[float]] = {}
        for row in legacy_rows:
            chunk_id = row.get("chunk_id")
            raw_vector = row.get("vector")
            if chunk_id in vectors or raw_vector is None:
                return DocumentMigrationResult(document_id, "reindex_required", 0, "legacy vectors are incomplete")
            vector = [float(value) for value in raw_vector]
            if len(vector) != EMBED_DIM or not all(math.isfinite(value) for value in vector):
                return DocumentMigrationResult(
                    document_id, "reindex_required", 0, "legacy vector dimension is incompatible"
                )
            vectors[chunk_id] = vector
        expected_ids = {str(chunk.get("chunk_id", "")) for chunk in legacy_chunks}
        if len(legacy_rows) != len(legacy_chunks) or set(vectors) != expected_ids:
            return DocumentMigrationResult(document_id, "reindex_required", 0, "legacy vector rows do not match chunks")

        collection = await self.repo.get_collection(uuid.UUID(int=0), collection_id)
        generation = f"migrated-v1-{document_id}"
        migrated_chunks: list[KbChunk] = []
        for record in legacy_chunks:
            content = str(record.get("content", ""))
            if not content.strip():
                return DocumentMigrationResult(document_id, "reindex_required", 0, "legacy chunk text is empty")
            section_path = tuple(record.get("section_path", ()))
            retrieval_text = "\n".join(
                part for part in (document.filename, " / ".join(section_path), content) if part
            )
            migrated_chunks.append(
                KbChunk(
                    id=uuid.UUID(record["chunk_id"]),
                    document_id=document_id,
                    collection_id=collection_id,
                    org_id=document.org_id,
                    chunk_index=int(record.get("chunk_index", 0)),
                    content=content,
                    embedding=vectors[str(record["chunk_id"])],
                    embedding_model=collection.embedding_model if collection else None,
                    generation=generation,
                    retrieval_text=retrieval_text,
                    section_path=section_path,
                    start_offset=int(record.get("start_offset", 0)),
                    end_offset=int(record.get("end_offset", len(content))),
                    token_count=int(record.get("token_count", 0)),
                    chunking_strategy=str(record.get("chunking_strategy", "legacy")),
                )
            )

        wrote_generation = False
        activated_lance = False
        try:
            wrote_generation = True
            await self.repo.lance.write_generation(migrated_chunks, active=False)
            validation = await self.repo.lance.validate_generation(document_id, generation, len(migrated_chunks))
            if (
                not validation.row_count_matches
                or validation.unique_chunk_count != len(migrated_chunks)
                or not validation.vector_dimensions_valid
                or validation.empty_text_count
            ):
                raise RuntimeError("migrated generation validation failed")
            await self.repo.lance.set_generation_active(document_id, generation, True)
            activated_lance = True
            await KbGenerationService(repo=self.repo).activate(document, generation, migrated_chunks)
        except asyncio.CancelledError:
            # The manifest update in activate() may have committed immediately before
            # cancellation. Keep the deterministic generation; manifest visibility
            # protects readers and the next migration attempt can safely upsert it.
            raise
        except Exception as exc:  # noqa: BLE001  keep v1 manifest/table untouched on migration failure
            if wrote_generation:
                await self._rollback_generation_if_unreferenced(
                    collection_id, document_id, generation, deactivate=activated_lance
                )
            return DocumentMigrationResult(document_id, "failed", 0, type(exc).__name__)

        return DocumentMigrationResult(document_id, "migrated", len(migrated_chunks))

    async def _rollback_generation(
        self, document_id: uuid.UUID, generation: str, *, deactivate: bool
    ) -> None:
        if deactivate:
            try:
                await self.repo.lance.set_generation_active(document_id, generation, False)
            finally:
                await self.repo.lance.delete_generation(document_id, generation)
        else:
            await self.repo.lance.delete_generation(document_id, generation)

    async def _rollback_generation_if_unreferenced(
        self,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
        generation: str,
        *,
        deactivate: bool,
    ) -> None:
        try:
            manifest = await self.repo.manifests.load(collection_id)
        except Exception:  # noqa: BLE001  an unreadable manifest is safer with an orphan than lost vectors
            return
        document = manifest["documents"].get(str(document_id), {})
        if document.get("active_generation") == generation:
            return
        await self._rollback_generation(document_id, generation, deactivate=deactivate)

    async def migrate_all(self) -> MigrationReport:
        ledger = await self._load_ledger()
        if ledger.get("completed_at") and not ledger.get("legacy_fallback_required"):
            return self._report(ledger, complete=True)

        ledger.setdefault("version", 1)
        if not ledger.get("started_at"):
            ledger["started_at"] = datetime.now(UTC).isoformat()
        ledger.setdefault("documents", {})
        ledger["completed_at"] = None
        ledger["last_error"] = None
        await self._save_ledger(ledger)

        entries = dict(ledger["documents"])
        seen: set[str] = set()
        for collection_dir in _collection_dirs(self.repo.store):
            collection_id = uuid.UUID(collection_dir.name)
            try:
                manifest = await self.repo.manifests.load(collection_id)
            except Exception as exc:  # noqa: BLE001  isolate corrupt collections and keep legacy fallback enabled
                key = f"collection:{collection_id}"
                seen.add(key)
                entries[key] = {
                    "collection_id": str(collection_id),
                    "status": "failed",
                    "chunk_count": 0,
                    "reason": type(exc).__name__,
                }
                ledger["documents"] = entries
                ledger["last_error"] = type(exc).__name__
                await self._save_ledger(ledger)
                continue

            for document_key, document in manifest["documents"].items():
                if document.get("deleted_at") or document.get("status") != "indexed":
                    continue
                seen.add(document_key)
                previous = entries.get(document_key, {})
                try:
                    document_id = uuid.UUID(document_key)
                    async with DOCUMENT_INDEX_LOCKS.acquire(document_id):
                        result = await self._migrate_document_locked(
                            collection_id,
                            document_id,
                            manifest=manifest,
                            document_data=document,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001  record a resumable failure for this document
                    entries[document_key] = {
                        "collection_id": str(collection_id),
                        "status": "failed",
                        "chunk_count": 0,
                        "reason": type(exc).__name__,
                    }
                else:
                    status = result.status
                    if status == "skipped" and previous.get("status") == "migrated":
                        status = "migrated"
                    entries[document_key] = {
                        "collection_id": str(collection_id),
                        "status": status,
                        "chunk_count": result.chunk_count,
                        "reason": result.reason,
                    }
                ledger["documents"] = entries
                await self._save_ledger(ledger)

        ledger["documents"] = {key: value for key, value in entries.items() if key in seen}
        report = self._report(ledger, complete=False)
        ledger["legacy_fallback_required"] = bool(
            report.reindex_required or report.failed or await self.repo.has_legacy_active_documents()
        )
        ledger["completed_at"] = None if ledger["legacy_fallback_required"] else datetime.now(UTC).isoformat()
        if not ledger["legacy_fallback_required"]:
            ledger["last_error"] = None
        elif report.reindex_required or report.failed:
            ledger["last_error"] = next(
                (
                    entry.get("reason")
                    for entry in ledger["documents"].values()
                    if entry.get("status") in {"reindex_required", "failed"}
                ),
                "legacy documents still require migration",
            )
        await self._save_ledger(ledger)
        return self._report(ledger, complete=not ledger["legacy_fallback_required"])

    async def _load_ledger(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {
                "version": 1,
                "started_at": None,
                "completed_at": None,
                "documents": {},
                "last_error": None,
                "legacy_fallback_required": False,
            }
        raw = await asyncio.to_thread(self.ledger_path.read_text, encoding="utf-8")
        ledger = json.loads(raw)
        required = {
            "version",
            "started_at",
            "completed_at",
            "documents",
            "last_error",
            "legacy_fallback_required",
        }
        if (
            not isinstance(ledger, dict)
            or not required.issubset(ledger)
            or ledger.get("version") != 1
            or not isinstance(ledger.get("documents"), dict)
        ):
            raise ValueError("invalid KB migration ledger")
        return ledger

    async def _save_ledger(self, ledger: Mapping[str, Any]) -> None:
        async with self._ledger_lock:
            await asyncio.to_thread(self._atomic_write_ledger, dict(ledger))

    def _atomic_write_ledger(self, ledger: dict[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(ledger, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(dir=str(self.ledger_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.ledger_path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def _report(ledger: Mapping[str, Any], *, complete: bool) -> MigrationReport:
        entries = ledger.get("documents", {}).values()
        counts = {status: 0 for status in ("migrated", "skipped", "reindex_required", "failed")}
        for entry in entries:
            status = entry.get("status")
            if status in counts:
                counts[status] += 1
        return MigrationReport(
            total=sum(counts.values()),
            migrated=counts["migrated"],
            skipped=counts["skipped"],
            reindex_required=counts["reindex_required"],
            failed=counts["failed"],
            complete=complete,
        )
