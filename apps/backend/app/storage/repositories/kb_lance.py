"""Persistent LanceDB storage for versioned knowledge-base chunks."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.storage.models.kb import EMBED_DIM, KbChunk

LANCE_TABLE_NAME = "chunks_v2"
RETRIEVAL_SCHEMA_VERSION = 2
FTS_INDEX_NAME = "retrieval_text_fts_v1"
_FTS_FIELD = "retrieval_text"


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    collection_id: uuid.UUID
    generation: str
    content: str
    channel_score: float


@dataclass(frozen=True, slots=True)
class GenerationValidation:
    row_count: int
    row_count_matches: bool
    unique_chunk_count: int
    vector_dimensions_valid: bool
    empty_text_count: int


_DATABASES: dict[Path, Any] = {}
_TABLES: dict[Path, Any] = {}
_FTS_LOCKS: dict[Path, threading.Lock] = {}
_CACHE_LOCK = threading.Lock()


def reset_lance_store() -> None:
    """Drop cached Lance handles so tests can isolate temporary KB roots."""
    with _CACHE_LOCK:
        _DATABASES.clear()
        _TABLES.clear()
        _FTS_LOCKS.clear()


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _filter(collection_ids: list[uuid.UUID] | None) -> str:
    expression = "active = true"
    if collection_ids:
        values = ", ".join(_quote(str(value)) for value in collection_ids)
        expression += f" AND collection_id IN ({values})"
    return expression


class KbLanceStore:
    """Async façade over synchronous local LanceDB operations."""

    def __init__(self, kb_root: Path | str) -> None:
        self.kb_root = Path(kb_root).expanduser().resolve()
        self._mutation_count = 0
        self._mutation_lock = threading.Lock()

    @property
    def mutation_count(self) -> int:
        with self._mutation_lock:
            return self._mutation_count

    def _record_mutations(self, count: int = 1) -> None:
        with self._mutation_lock:
            self._mutation_count += count

    def _table(self) -> Any:
        with _CACHE_LOCK:
            table = _TABLES.get(self.kb_root)
            if table is not None:
                return table

            import lancedb
            import pyarrow as pa

            self.kb_root.mkdir(parents=True, exist_ok=True)
            db = _DATABASES.get(self.kb_root)
            if db is None:
                db = lancedb.connect(str(self.kb_root / "vectors.lance"))
                _DATABASES[self.kb_root] = db
            if LANCE_TABLE_NAME in db.list_tables().tables:
                table = db.open_table(LANCE_TABLE_NAME)
            else:
                schema = pa.schema(
                    [
                        pa.field("chunk_id", pa.string()),
                        pa.field("document_id", pa.string()),
                        pa.field("collection_id", pa.string()),
                        pa.field("org_id", pa.string()),
                        pa.field("generation", pa.string()),
                        pa.field("chunk_index", pa.int32()),
                        pa.field("content", pa.string()),
                        pa.field("retrieval_text", pa.string()),
                        pa.field("section_path", pa.list_(pa.string())),
                        pa.field("start_offset", pa.int64()),
                        pa.field("end_offset", pa.int64()),
                        pa.field("token_count", pa.int32()),
                        pa.field("chunking_strategy", pa.string()),
                        pa.field("embedding_model", pa.string()),
                        pa.field("schema_version", pa.int32()),
                        pa.field("active", pa.bool_()),
                        pa.field("created_at", pa.timestamp("us", tz="UTC")),
                        pa.field("vector", pa.list_(pa.float32(), EMBED_DIM)),
                    ]
                )
                table = db.create_table(LANCE_TABLE_NAME, schema=schema)
            _TABLES[self.kb_root] = table
            return table

    def _ensure_ready(self, tokenizer: str) -> None:
        with _CACHE_LOCK:
            index_lock = _FTS_LOCKS.setdefault(self.kb_root, threading.Lock())
        with index_lock:
            table = self._table()
            indexes = list(table.list_indices())
            if any(
                index.name == FTS_INDEX_NAME and list(index.columns) == [_FTS_FIELD]
                for index in indexes
            ):
                return
            from lancedb.index import FTS

            table.create_index(
                _FTS_FIELD,
                config=FTS(
                    base_tokenizer=tokenizer,
                    with_position=True,
                    lower_case=True,
                    stem=False,
                    remove_stop_words=False,
                    ascii_folding=True,
                ),
                replace=False,
                name=FTS_INDEX_NAME,
            )

    async def ensure_ready(self, tokenizer: str = "icu") -> None:
        await asyncio.to_thread(self._ensure_ready, tokenizer)

    def _write_generation(self, chunks: list[KbChunk], active: bool) -> None:
        if not chunks:
            return
        self._ensure_ready("icu")
        import numpy as np

        records = []
        for chunk in chunks:
            vector = chunk.embedding
            if vector is None:
                raise ValueError("embedding vector is required for chunks_v2")
            if len(vector) != EMBED_DIM:
                raise ValueError(f"embedding dimension must be {EMBED_DIM}, got {len(vector)}")
            records.append(
                {
                    "chunk_id": str(chunk.id),
                    "document_id": str(chunk.document_id),
                    "collection_id": str(chunk.collection_id),
                    "org_id": str(chunk.org_id),
                    "generation": chunk.generation,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "retrieval_text": chunk.retrieval_text or chunk.content,
                    "section_path": list(chunk.section_path),
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                    "token_count": chunk.token_count,
                    "chunking_strategy": chunk.chunking_strategy,
                    "embedding_model": getattr(chunk, "embedding_model", None) or "",
                    "schema_version": RETRIEVAL_SCHEMA_VERSION,
                    "active": active,
                    "created_at": chunk.created_at,
                    "vector": np.asarray(vector, dtype=np.float32).tolist(),
                }
            )
        self._table().merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all().execute(
            records
        )
        self._record_mutations(len(records))

    async def write_generation(self, chunks: Sequence[KbChunk], *, active: bool = False) -> None:
        await asyncio.to_thread(self._write_generation, list(chunks), active)

    def _generation_rows(self, document_id: uuid.UUID, generation: str) -> list[dict[str, Any]]:
        condition = f"document_id = {_quote(str(document_id))} AND generation = {_quote(generation)}"
        return self._table().search().where(condition).select(["chunk_id", "retrieval_text", "vector"]).to_list()

    def _validate_generation(
        self, document_id: uuid.UUID, generation: str, expected_count: int
    ) -> GenerationValidation:
        rows = self._generation_rows(document_id, generation)
        ids = {row["chunk_id"] for row in rows}
        dimensions_valid = all(
            row.get("vector") is not None and len(row["vector"]) == EMBED_DIM for row in rows
        )
        empty_text_count = sum(1 for row in rows if not (row.get(_FTS_FIELD) or "").strip())
        return GenerationValidation(
            row_count=len(rows),
            row_count_matches=len(rows) == expected_count,
            unique_chunk_count=len(ids),
            vector_dimensions_valid=dimensions_valid,
            empty_text_count=empty_text_count,
        )

    async def validate_generation(
        self, document_id: uuid.UUID, generation: str, expected_count: int
    ) -> GenerationValidation:
        return await asyncio.to_thread(self._validate_generation, document_id, generation, expected_count)

    def _set_generation_active(self, document_id: uuid.UUID, generation: str, active: bool) -> None:
        self._table().update(
            where=f"document_id = {_quote(str(document_id))} AND generation = {_quote(generation)}",
            values={"active": active},
        )
        self._record_mutations()

    async def set_generation_active(self, document_id: uuid.UUID, generation: str, active: bool) -> None:
        await asyncio.to_thread(self._set_generation_active, document_id, generation, active)

    def _delete_generation(self, document_id: uuid.UUID, generation: str) -> None:
        self._table().delete(
            f"document_id = {_quote(str(document_id))} AND generation = {_quote(generation)}"
        )
        self._record_mutations()

    async def delete_generation(self, document_id: uuid.UUID, generation: str) -> None:
        await asyncio.to_thread(self._delete_generation, document_id, generation)

    def _delete_document(self, document_id: uuid.UUID) -> None:
        self._table().delete(f"document_id = {_quote(str(document_id))}")
        self._record_mutations()

    async def delete_document(self, document_id: uuid.UUID) -> None:
        await asyncio.to_thread(self._delete_document, document_id)

    @staticmethod
    def _candidate(row: dict[str, Any], score: float) -> RetrievalCandidate:
        return RetrievalCandidate(
            chunk_id=uuid.UUID(row["chunk_id"]),
            document_id=uuid.UUID(row["document_id"]),
            collection_id=uuid.UUID(row["collection_id"]),
            generation=row["generation"],
            content=row["content"],
            channel_score=float(score),
        )

    def _vector_search(
        self, query_vector: list[float], collection_ids: list[uuid.UUID], limit: int
    ) -> list[RetrievalCandidate]:
        if not query_vector or self._table().count_rows() == 0:
            return []
        hits = (
            self._table()
            .search(query_vector)
            .metric("cosine")
            .where(_filter(collection_ids))
            .limit(limit)
            .to_list()
        )
        return [self._candidate(row, row["_distance"]) for row in hits]

    async def vector_search(
        self, query_vector: list[float], collection_ids: list[uuid.UUID], limit: int
    ) -> list[RetrievalCandidate]:
        return await asyncio.to_thread(self._vector_search, query_vector, collection_ids, limit)

    def _fts_search(
        self, query: str, collection_ids: list[uuid.UUID], limit: int
    ) -> list[RetrievalCandidate]:
        if not query.strip() or self._table().count_rows() == 0:
            return []
        hits = (
            self._table()
            .search(query, query_type="fts", fts_columns=_FTS_FIELD)
            .where(_filter(collection_ids))
            .limit(limit)
            .to_list()
        )
        return [self._candidate(row, row["_score"]) for row in hits]

    async def fts_search(
        self, query: str, collection_ids: list[uuid.UUID], limit: int
    ) -> list[RetrievalCandidate]:
        await self.ensure_ready()
        return await asyncio.to_thread(self._fts_search, query, collection_ids, limit)

    def _optimize(self) -> None:
        self._table().optimize()
        with self._mutation_lock:
            self._mutation_count = 0

    async def optimize(self) -> None:
        await asyncio.to_thread(self._optimize)

    def _health(self) -> dict[str, Any]:
        table = self._table()
        indexes = list(table.list_indices())
        fts_ready = any(
            index.name == FTS_INDEX_NAME and list(index.columns) == [_FTS_FIELD]
            for index in indexes
        )
        return {
            "table": LANCE_TABLE_NAME,
            "schema_version": RETRIEVAL_SCHEMA_VERSION,
            "row_count": table.count_rows(),
            "fts_ready": fts_ready,
            "fts_index": FTS_INDEX_NAME if fts_ready else None,
        }

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._health)
