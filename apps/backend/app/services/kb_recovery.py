"""Startup reconciliation and low-frequency maintenance for KB generations."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.services.kb_generation import DOCUMENT_INDEX_LOCKS, KbGenerationService
from app.storage.file.store import get_store
from app.storage.kb.manifest import LEGACY_GENERATION
from app.storage.repositories.kb import KbRepository, _collection_dirs

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    scanned: int
    repaired: int
    cleanup_pending: int
    repair_required: int
    errors: tuple[str, ...]


async def reconcile_kb_index() -> RecoveryReport:
    repo = KbRepository()
    scanned = 0
    repaired = 0
    cleanup_pending = 0
    repair_required = 0
    errors: list[str] = []
    generation_service = KbGenerationService(repo=repo)

    for collection_dir in _collection_dirs(repo.store):
        collection_id = uuid.UUID(collection_dir.name)
        try:
            manifest = await repo.manifests.load(collection_id)
        except Exception as exc:  # noqa: BLE001  one corrupt collection must not block others
            errors.append(f"{collection_id}:{type(exc).__name__}")
            logger.warning("KB recovery failed collection_id=%s error_type=%s", collection_id, type(exc).__name__)
            continue

        for document_key in list(manifest["documents"]):
            scanned += 1
            document_id = uuid.UUID(document_key)
            async with DOCUMENT_INDEX_LOCKS.acquire(document_id):
                try:
                    changed = await _reconcile_document(
                        repo, generation_service, collection_id, document_id
                    )
                    repaired += int(changed)
                    current = await repo.manifests.load(collection_id)
                    state = current["documents"].get(document_key, {})
                    cleanup_pending += int(state.get("index_state") == "cleanup_pending")
                    repair_required += int(state.get("index_state") == "repair_required")
                except Exception as exc:  # noqa: BLE001  isolate per-document recovery
                    errors.append(f"{collection_id}/{document_id}:{type(exc).__name__}")
                    try:
                        current = await repo.manifests.load(collection_id)
                        state = current["documents"].get(document_key, {})
                    except Exception:  # noqa: BLE001
                        state = manifest["documents"].get(document_key, {})
                    logger.warning(
                        "KB recovery failed collection_id=%s document_id=%s error_type=%s",
                        collection_id,
                        document_id,
                        type(exc).__name__,
                    )
                    cleanup_pending += int(state.get("index_state") == "cleanup_pending")
    return RecoveryReport(scanned, repaired, cleanup_pending, repair_required, tuple(errors))


async def _reconcile_document(
    repo: KbRepository,
    generation_service: KbGenerationService,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
) -> bool:
    manifest = await repo.manifests.load(collection_id)
    document = manifest["documents"].get(str(document_id))
    if document is None:
        return False
    before_state = document.get("index_state", "idle")

    if document.get("deleted_at") or document.get("status") == "archived":
        await repo.cleanup_document_index(
            document_id,
            collection_id,
            delete_source=bool(document.get("deleted_at")),
        )
        return bool(manifest["chunks"].get(str(document_id))) or before_state == "cleanup_pending"

    repaired = False
    building_generation = document.get("building_generation")
    if building_generation:
        try:
            await repo.lance.delete_generation(document_id, building_generation)
        except Exception as exc:  # noqa: BLE001  keep the marker so the next recovery can retry
            has_active = bool(document.get("active_generation"))
            await _set_document_state(
                repo,
                collection_id,
                document_id,
                status="indexed" if has_active else "failed",
                index_state="cleanup_pending",
                last_index_error=type(exc).__name__,
                **({} if has_active else {"error": "未完成的索引代清理失败"}),
            )
            raise

        def clear_building(index: dict[str, Any]) -> None:
            state = index["documents"][str(document_id)]
            state["building_generation"] = None
            has_active = bool(state.get("active_generation"))
            state["status"] = "indexed" if has_active else "failed"
            state["index_state"] = "ready" if has_active else "failed"
            if not has_active:
                state["error"] = "索引任务在服务重启时中断"
            index["chunks"].get(str(document_id), {}).pop(building_generation, None)

        await repo.update_manifest(collection_id, clear_building, version=2)
        repaired = True
        manifest = await repo.manifests.load(collection_id)
        document = manifest["documents"][str(document_id)]

    active_generation = document.get("active_generation")
    generation_map = manifest["chunks"].get(str(document_id), {})
    if isinstance(generation_map, list):
        generation_map = {LEGACY_GENERATION: generation_map}

    stale_generations = [
        generation
        for generation in generation_map
        if generation != active_generation and generation != LEGACY_GENERATION
    ]
    for generation in stale_generations:
        try:
            await generation_service.cleanup_generation(document_id, generation)
            repaired = True
        except Exception as exc:  # noqa: BLE001  leave metadata for the next recovery attempt
            await _set_document_state(
                repo,
                collection_id,
                document_id,
                index_state="cleanup_pending",
                last_index_error=type(exc).__name__,
            )
            raise

    manifest = await repo.manifests.load(collection_id)
    document = manifest["documents"][str(document_id)]
    active_generation = document.get("active_generation")
    if stale_generations and document.get("index_state") == "cleanup_pending":
        next_state = "ready" if active_generation else ("failed" if document.get("status") == "failed" else "idle")
        await _set_document_state(
            repo,
            collection_id,
            document_id,
            index_state=next_state,
            last_index_error=None,
        )
        repaired = True
        manifest = await repo.manifests.load(collection_id)
        document = manifest["documents"][str(document_id)]
        active_generation = document.get("active_generation")
    if active_generation and active_generation != LEGACY_GENERATION:
        generation_map = manifest["chunks"].get(str(document_id), {})
        records = generation_map.get(active_generation, []) if isinstance(generation_map, dict) else []
        validation = await repo.lance.validate_generation(document_id, active_generation, len(records))
        valid = (
            validation.row_count_matches
            and validation.unique_chunk_count == len(records)
            and validation.vector_dimensions_valid
            and validation.empty_text_count == 0
        )
        if not valid:
            await _set_document_state(
                repo,
                collection_id,
                document_id,
                index_state="repair_required",
                last_index_error="active generation rows do not match the manifest",
            )
            return repaired
        if document.get("index_state") == "repair_required":
            await _set_document_state(
                repo,
                collection_id,
                document_id,
                index_state="ready",
                last_index_error=None,
            )
            repaired = True
    elif document.get("status") == "indexed" and not active_generation:
        await _set_document_state(
            repo,
            collection_id,
            document_id,
            index_state="repair_required",
            last_index_error="indexed document has no active generation",
        )
    elif stale_generations or before_state == "cleanup_pending":
        next_state = "failed" if document.get("status") == "failed" else "idle"
        await _set_document_state(
            repo,
            collection_id,
            document_id,
            index_state=next_state,
            last_index_error=None,
        )
        repaired = True
    return repaired


async def _set_document_state(
    repo: KbRepository,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    **fields: Any,
) -> None:
    def update(manifest: dict[str, Any]) -> None:
        manifest["documents"][str(document_id)].update(fields)

    await repo.update_manifest(collection_id, update, version=2)


async def kb_maintenance_loop(settings: Settings) -> None:
    """Periodically retry cleanup and optimize only after enough data mutations."""
    interval = max(1, settings.kb_maintenance_interval_s)
    threshold = max(1, settings.kb_optimize_min_mutations)
    while True:
        await asyncio.sleep(interval)
        try:
            report = await reconcile_kb_index()
            if report.errors:
                logger.warning("KB periodic recovery errors=%d", len(report.errors))
            lance = get_store().kb_lance_store
            if lance is not None and lance.mutation_count >= threshold:
                await lance.optimize()
                logger.info("KB Lance optimize completed mutation_threshold=%d", threshold)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  maintenance must not terminate the app
            logger.warning("KB maintenance failed error_type=%s", type(exc).__name__)
