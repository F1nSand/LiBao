"""Atomic, version-aware persistence for per-collection knowledge-base indexes."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

LEGACY_GENERATION = "legacy-v1"


class ManifestCorruptError(RuntimeError):
    """Raised when neither the primary manifest nor its backup can be read."""


def empty_manifest() -> dict[str, Any]:
    return {"version": 2, "documents": {}, "chunks": {}}


def normalize_manifest(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a v2 in-memory view while retaining the disk format for round trips."""
    source_version = int(raw.get("version", 1))
    if source_version not in (1, 2):
        raise ValueError(f"unsupported KB manifest version: {source_version}")

    normalized = copy.deepcopy(dict(raw))
    documents = normalized.get("documents", {})
    chunks = normalized.get("chunks", {})
    if not isinstance(documents, dict) or not isinstance(chunks, dict):
        raise ValueError("KB manifest documents and chunks must be objects")

    generation_chunks: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for document_id, document_chunks in chunks.items():
        if isinstance(document_chunks, list):
            generation_chunks[document_id] = {LEGACY_GENERATION: copy.deepcopy(document_chunks)}
        elif isinstance(document_chunks, dict):
            generation_chunks[document_id] = copy.deepcopy(document_chunks)
        else:
            raise ValueError(f"invalid chunk generations for document {document_id}")

    for document_id, document in documents.items():
        if not isinstance(document, dict):
            raise ValueError(f"invalid document record for {document_id}")
        document.setdefault("active_generation", None)
        document.setdefault("building_generation", None)
        document.setdefault("index_state", "idle")
        document.setdefault("chunking_version", None)
        document.setdefault("retrieval_schema_version", 1)
        document.setdefault("embedding_dimension", None)
        document.setdefault("last_indexed_at", None)
        document.setdefault("last_index_error", None)
        generations = generation_chunks.get(document_id, {})
        if (
            source_version == 1
            and document.get("status") == "indexed"
            and not document.get("deleted_at")
            and document.get("active_generation") is None
            and LEGACY_GENERATION in generations
        ):
            document["active_generation"] = LEGACY_GENERATION

    normalized["version"] = 2
    normalized["documents"] = documents
    normalized["chunks"] = generation_chunks
    normalized["_source_version"] = source_version
    return normalized


class KbManifestStore:
    """Per-collection JSON manifests with atomic writes and serialized updates."""

    _locks: dict[tuple[int, str, str], asyncio.Lock] = {}

    def __init__(self, kb_root: Path | str) -> None:
        self.kb_root = Path(kb_root)

    def path_for(self, collection_id: uuid.UUID) -> Path:
        return self.kb_root / str(collection_id) / "index.json"

    async def load(self, collection_id: uuid.UUID) -> dict[str, Any]:
        path = self.path_for(collection_id)
        backup = path.with_suffix(path.suffix + ".bak")
        if not path.exists():
            if not backup.exists():
                return empty_manifest() | {"_source_version": 2}
            try:
                recovered = normalize_manifest(json.loads(backup.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ManifestCorruptError(f"KB manifest and backup are unreadable: {path}") from exc
            return self._mark_repair_required(recovered)

        try:
            return normalize_manifest(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as primary_error:
            try:
                recovered = normalize_manifest(json.loads(backup.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as backup_error:
                raise ManifestCorruptError(f"KB manifest and backup are unreadable: {path}") from backup_error
            recovered["primary_error"] = str(primary_error)
            return self._mark_repair_required(recovered)

    async def save(
        self, collection_id: uuid.UUID, manifest: Mapping[str, Any], *, version: int | None = None
    ) -> None:
        path = self.path_for(collection_id)
        source_version = int(version or manifest.get("_source_version", manifest.get("version", 2)))
        disk_manifest = self._serialize(manifest, source_version)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            try:
                current_bytes = path.read_bytes()
                json.loads(current_bytes)
            except (OSError, json.JSONDecodeError):
                pass
            else:
                self._atomic_write(path.with_suffix(path.suffix + ".bak"), current_bytes)

        payload = json.dumps(disk_manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._atomic_write(path, payload)

    async def update(
        self,
        collection_id: uuid.UUID,
        mutate: Callable[[dict[str, Any]], None],
        *,
        version: int | None = None,
    ) -> dict[str, Any]:
        loop_id = id(asyncio.get_running_loop())
        key = (loop_id, str(self.kb_root.resolve()), str(collection_id))
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            manifest = await self.load(collection_id)
            mutate(manifest)
            if version is not None:
                manifest["_source_version"] = version
            await self.save(collection_id, manifest, version=version)
            return manifest

    @staticmethod
    def _serialize(manifest: Mapping[str, Any], version: int) -> dict[str, Any]:
        if version not in (1, 2):
            raise ValueError(f"unsupported KB manifest version: {version}")
        data = copy.deepcopy(dict(manifest))
        data.pop("_source_version", None)
        data.pop("repair_required", None)
        data.pop("primary_error", None)
        if version == 1:
            legacy_chunks: dict[str, list[dict[str, Any]]] = {}
            for document_id, generations in data.get("chunks", {}).items():
                if isinstance(generations, list):
                    legacy_chunks[document_id] = generations
                elif set(generations) <= {LEGACY_GENERATION}:
                    legacy_chunks[document_id] = generations.get(LEGACY_GENERATION, [])
                else:
                    raise ValueError("cannot persist non-legacy generations in a v1 manifest")
            data["chunks"] = legacy_chunks
        data["version"] = version
        return data

    @staticmethod
    def _mark_repair_required(manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["repair_required"] = True
        for document in manifest["documents"].values():
            document["index_state"] = "repair_required"
        return manifest

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        fd, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
