"""知识库数据访问（《02》数据模型 §3.6）。集合/文档软删；分块硬删重建（派生数据）。

本地单机化：
- 集合：.agent/kb_collections.json（FileTable）
- 文档+分块：kb/<collection_id>/index.json（documents/chunks 内嵌）+ documents/<doc_id>.md（原文）
- 向量：kb/vectors.lance（LanceDB 单表，chunk_id 主键，merge_insert 增量 upsert）
- BM25：FileStore.bm25（仅为尚未迁移的 v1 文档提供兼容回退）

混合检索保留 RRF k=60、rerank 和降级链，并在最终返回前校验 manifest 可见性。
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.embeddings import EmbeddingService
from app.core.rerank import RerankService
from app.storage.file.store import get_store
from app.storage.kb.manifest import LEGACY_GENERATION, KbManifestStore
from app.storage.models.kb import KbChunk, KbCollection, KbDocument

logger = logging.getLogger(__name__)

_CJK = re.compile(r"([一-鿿])")
_RRF_K = 60  # 倒数排名融合常数（《02》后端设计 §9.1）
_RERANK_CANDIDATES = 20  # rerank 粗排候选数（RRF 取 top 20 → Cross-Encoder 精排 → top_k）


def space_cjk(text: str) -> str:
    """CJK 逐字插空格（与旧迁移 0004 GENERATED tsvector 表达式一致——BM25 查询侧同一变换）。"""
    return _CJK.sub(r"\1 ", text)


def _collection_dirs(store) -> list:
    """kb_root 下的集合目录（跳过 vectors.lance 等非 UUID 目录）。"""
    out = []
    if not store.kb_root.is_dir():
        return out
    for entry in store.kb_root.iterdir():
        if entry.is_dir():
            try:
                uuid.UUID(entry.name)
            except ValueError:
                continue
            out.append(entry)
    return out


def _active_chunk_records(index: dict[str, Any], document_id: str) -> list[dict[str, Any]]:
    """Return legacy chunks or the v2 generation selected by the document manifest."""
    chunks = index["chunks"].get(document_id, [])
    if isinstance(chunks, list):
        return chunks
    active_generation = index["documents"].get(document_id, {}).get("active_generation")
    return chunks.get(active_generation, []) if active_generation else []


# ---- LanceDB（模块级缓存连接，kb_root 固定）----

_lance_db: Any = None
_lance_table: Any = None


def _get_lance_table() -> Any:
    """kb/vectors.lance 单表（首次惰性建表；schema 与 P0.5 验证一致）。"""
    global _lance_db, _lance_table
    if _lance_table is not None:
        return _lance_table
    import lancedb
    import pyarrow as pa

    store = get_store()
    if _lance_db is None:
        _lance_db = lancedb.connect(str(store.kb_root / "vectors.lance"))
    name = "vectors"
    if name in _lance_db.table_names():
        _lance_table = _lance_db.open_table(name)
    else:
        schema = pa.schema(
            [
                pa.field("chunk_id", pa.string()),
                pa.field("content", pa.string()),
                pa.field("collection_id", pa.string()),
                pa.field("document_id", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("status", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 1024)),
            ]
        )
        _lance_table = _lance_db.create_table(name, schema=schema)
    return _lance_table


def reset_lance() -> None:
    """重置模块级 LanceDB 缓存（测试隔离）。"""
    global _lance_db, _lance_table
    _lance_db = None
    _lance_table = None


class KbRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.store = get_store()
        self.table = self.store.table("kb_collections")
        self.manifests = KbManifestStore(self.store.kb_root)
        if self.store.kb_lance_store is None:
            from app.storage.repositories.kb_lance import KbLanceStore

            self.store.kb_lance_store = KbLanceStore(self.store.kb_root)
        self.lance = self.store.kb_lance_store

    # ---- 集合 ----

    async def get_collection(self, org_id: uuid.UUID, collection_id: uuid.UUID) -> KbCollection | None:
        row = await self.table.get(collection_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        rows = await self.table.list(filter_fn=lambda c: c.name == name and c.deleted_at is None, limit=1)
        return len(rows) > 0

    async def document_counts(
        self, org_id: uuid.UUID, collection_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """各集合非软删文档数。"""
        out: dict[uuid.UUID, int] = {}
        for cid in collection_ids:
            index = await self._load_index(cid)
            n = sum(1 for d in index["documents"].values() if not d.get("deleted_at"))
            out[cid] = n
        return out

    async def list_collections(self, org_id: uuid.UUID) -> list[KbCollection]:
        return await self.table.list(
            filter_fn=lambda c: c.deleted_at is None, sort_key=lambda c: c.created_at, desc=True
        )

    async def create_collection(
        self, org_id: uuid.UUID, name: str, chunk_size: int, chunk_overlap: int, description: str = ""
    ) -> KbCollection:
        row = KbCollection(
            org_id=org_id, name=name, description=description, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        self.table.register(row)
        await self._save_index(row.id, {"version": 1, "documents": {}, "chunks": {}})
        return row

    async def soft_delete_collection(self, coll: KbCollection) -> None:
        coll.deleted_at = datetime.now(UTC)

    # ---- 集合目录 index.json ----

    def _index_path(self, collection_id: uuid.UUID):
        return self.manifests.path_for(collection_id)

    async def _load_index(self, collection_id: uuid.UUID) -> dict[str, Any]:
        index = await self.manifests.load(collection_id)
        if index.get("_source_version") == 1:
            index["chunks"] = {
                document_id: generations.get(LEGACY_GENERATION, [])
                if isinstance(generations, dict)
                else generations
                for document_id, generations in index["chunks"].items()
            }
        return index

    async def _save_index(self, collection_id: uuid.UUID, index: dict[str, Any]) -> None:
        await self.manifests.save(collection_id, index)

    async def _update_index(self, collection_id: uuid.UUID, mutate) -> dict[str, Any]:
        def compatible_update(index: dict[str, Any]) -> None:
            if index.get("_source_version") == 1:
                index["chunks"] = {
                    document_id: generations.get(LEGACY_GENERATION, [])
                    if isinstance(generations, dict)
                    else generations
                    for document_id, generations in index["chunks"].items()
                }
            mutate(index)

        return await self.manifests.update(collection_id, compatible_update)

    async def update_manifest(
        self,
        collection_id: uuid.UUID,
        mutate: Callable[[dict[str, Any]], None],
        *,
        version: int | None = None,
    ) -> dict[str, Any]:
        """Update the normalized manifest without applying v1 repository adapters."""
        return await self.manifests.update(collection_id, mutate, version=version)

    async def revoke_document_index(
        self,
        doc: KbDocument,
        *,
        status: str | None = None,
        deleted_at: datetime | None = None,
    ) -> None:
        """Atomically remove a document from retrieval before physical cleanup begins."""
        fields: dict[str, Any] = {"active_generation": None, "index_state": "cleanup_pending"}
        if status is not None:
            fields["status"] = status
        if deleted_at is not None:
            fields["deleted_at"] = deleted_at.isoformat()

        def revoke(manifest: dict[str, Any]) -> None:
            manifest["documents"][str(doc.id)].update(fields)

        await self.update_manifest(doc.collection_id, revoke, version=2)
        doc.active_generation = None
        doc.index_state = "cleanup_pending"
        if status is not None:
            doc.status = status
        if deleted_at is not None:
            doc.deleted_at = deleted_at

    async def cleanup_document_index(
        self,
        document_id: uuid.UUID,
        collection_id: uuid.UUID,
        *,
        delete_source: bool,
    ) -> None:
        """Delete both Lance layouts, then remove metadata and optional source text."""
        index = await self.manifests.load(collection_id)
        raw_generations = index["chunks"].get(str(document_id), {})
        generations = (
            {LEGACY_GENERATION: raw_generations}
            if isinstance(raw_generations, list)
            else raw_generations
        )
        legacy_ids = [
            chunk["chunk_id"]
            for generation, chunks in generations.items()
            if generation == LEGACY_GENERATION
            for chunk in chunks
            if chunk.get("chunk_id")
        ]
        try:
            await self.lance.delete_document(document_id)
            if legacy_ids:
                await self._lance_delete_document(str(document_id), legacy_ids, raise_errors=True)
            if delete_source:
                source_path = (
                    self.store.kb_root
                    / str(collection_id)
                    / "documents"
                    / f"{document_id}.md"
                )
                source_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001  manifest 已撤销可见性，后台可重试物理清理
            await self._set_cleanup_pending(document_id, collection_id, exc)
            raise

        def clear_metadata(manifest: dict[str, Any]) -> None:
            manifest["chunks"].pop(str(document_id), None)
            doc_state = manifest["documents"].get(str(document_id))
            if doc_state is not None:
                doc_state["building_generation"] = None
                doc_state["index_state"] = "idle"
                doc_state["chunk_count"] = 0
                doc_state["last_index_error"] = None

        await self.update_manifest(collection_id, clear_metadata, version=2)

    async def _set_cleanup_pending(
        self, document_id: uuid.UUID, collection_id: uuid.UUID, error: Exception
    ) -> None:
        def mark(manifest: dict[str, Any]) -> None:
            doc_state = manifest["documents"].get(str(document_id))
            if doc_state is not None:
                doc_state["index_state"] = "cleanup_pending"
                doc_state["last_index_error"] = type(error).__name__

        await self.update_manifest(collection_id, mark, version=2)

    # ---- 文档 ----

    async def get_document(self, org_id: uuid.UUID, document_id: uuid.UUID) -> KbDocument | None:
        for coll_dir in _collection_dirs(self.store):
            index = await self._load_index(uuid.UUID(coll_dir.name))
            doc = index["documents"].get(str(document_id))
            if doc is not None:
                if doc.get("deleted_at"):
                    return None
                row = KbDocument.from_dict(doc)
                row.collection_id = uuid.UUID(coll_dir.name)
                return row
        return None

    async def list_documents(self, collection_id: uuid.UUID) -> list[KbDocument]:
        index = await self._load_index(collection_id)
        rows = []
        for d in index["documents"].values():
            if d.get("deleted_at"):
                continue
            row = KbDocument.from_dict(d)
            row.collection_id = collection_id
            rows.append(row)
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows

    async def create_document(
        self,
        *,
        collection_id: uuid.UUID,
        org_id: uuid.UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
        content: str,
    ) -> KbDocument:
        row = KbDocument(
            collection_id=collection_id,
            org_id=org_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            content=content,
            status="uploaded",
            chunk_count=0,
        )
        await self._update_index(
            collection_id,
            lambda index: index["documents"].__setitem__(str(row.id), row.to_dict()),
        )
        # 原文落盘（目标布局 documents/<doc_id>.md；文档原文即上传文本，小文件同步写可接受）
        md_path = self.store.kb_root / str(collection_id) / "documents" / f"{row.id}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(content, encoding="utf-8")
        return row

    async def soft_delete_document(self, doc: KbDocument) -> None:
        doc.deleted_at = datetime.now(UTC)
        await self.persist_document(doc)

    async def persist_document(self, doc: KbDocument) -> None:
        """文档状态/字段变更落盘（服务层直接赋值后调用；index.json 不走 FileTable）。"""
        def update_document(index: dict[str, Any]) -> None:
            existing = index["documents"].setdefault(str(doc.id), {})
            existing.update(doc.to_dict())

        await self._update_index(doc.collection_id, update_document)

    async def delete_chunks(self, document_id: uuid.UUID) -> None:
        """硬删分块（reindex 前清旧 / 文档删除）。"""
        for coll_dir in _collection_dirs(self.store):
            collection_id = uuid.UUID(coll_dir.name)
            current = await self._load_index(collection_id)
            if str(document_id) not in current["chunks"]:
                continue
            removed_chunks: list[dict[str, Any]] = []

            def remove_chunks(index: dict[str, Any], target: list[dict[str, Any]] = removed_chunks) -> None:
                removed = index["chunks"].pop(str(document_id), [])
                if isinstance(removed, dict):
                    for generation_chunks in removed.values():
                        target.extend(generation_chunks)
                else:
                    target.extend(removed)

            await self._update_index(collection_id, remove_chunks)
            if not removed_chunks:
                continue
            cids = [c["chunk_id"] for c in removed_chunks]
            await self._lance_delete_document(str(document_id), cids)
            self.store.bm25.rebuild(await self._bm25_corpus())
            return

    async def delete_collection_chunks(self, collection_id: uuid.UUID) -> None:
        """集合级分块硬删（集合软删时调用）。"""
        await self._update_index(collection_id, lambda index: index.__setitem__("chunks", {}))
        _get_lance_table().delete(f"collection_id = '{collection_id}'")
        self.store.bm25.rebuild(await self._bm25_corpus())

    async def _lance_delete_document(
        self, document_id: str, chunk_ids: list[str], *, raise_errors: bool = False
    ) -> None:
        if not chunk_ids:
            return
        try:
            _get_lance_table().delete(f"document_id = '{document_id}'")
        except Exception as exc:  # noqa: BLE001  表不存在/空表容错
            logger.debug("lance delete skip: %s", exc)
            if raise_errors:
                raise

    # ---- 分块 ----

    async def list_chunks(self, document_id: uuid.UUID) -> list[KbChunk]:
        for coll_dir in _collection_dirs(self.store):
            index = await self._load_index(uuid.UUID(coll_dir.name))
            chunks = _active_chunk_records(index, str(document_id))
            if chunks:
                rows = []
                for c in chunks:
                    row = KbChunk(
                        id=uuid.UUID(c["chunk_id"]),
                        document_id=document_id,
                        collection_id=uuid.UUID(coll_dir.name),
                        org_id=uuid.UUID(int=0),
                        chunk_index=c["chunk_index"],
                        content=c["content"],
                        generation=c.get("generation", LEGACY_GENERATION),
                        retrieval_text=c.get("retrieval_text", c["content"]),
                        section_path=tuple(c.get("section_path", ())),
                        start_offset=c.get("start_offset", 0),
                        end_offset=c.get("end_offset", 0),
                        token_count=c.get("token_count", 0),
                        chunking_strategy=c.get("chunking_strategy", "auto"),
                    )
                    rows.append(row)
                rows.sort(key=lambda c: c.chunk_index)
                return rows
        return []

    async def count_chunks(self, document_id: uuid.UUID) -> int:
        return len(await self.list_chunks(document_id))

    async def insert_chunks(self, rows: list[KbChunk]) -> None:
        """分块入库：index.json（文本+序号）+ LanceDB（向量）。"""
        if not rows:
            return
        collection_id = rows[0].collection_id
        chunks = [
            {
                "chunk_id": str(r.id),
                "document_id": str(r.document_id),
                "collection_id": str(r.collection_id),
                "chunk_index": r.chunk_index,
                "content": r.content,
                "generation": r.generation,
                "retrieval_text": r.retrieval_text or r.content,
                "section_path": list(r.section_path),
                "start_offset": r.start_offset,
                "end_offset": r.end_offset,
                "token_count": r.token_count,
                "chunking_strategy": r.chunking_strategy,
            }
            for r in rows
        ]

        def add_chunks(index: dict[str, Any]) -> None:
            document_id = str(rows[0].document_id)
            if index.get("_source_version") == 1:
                index["chunks"][document_id] = chunks
            else:
                index["chunks"].setdefault(document_id, {})[rows[0].generation] = chunks

        await self._update_index(
            collection_id,
            add_chunks,
        )
        # LanceDB 增量 upsert（merge_insert：同主键更新，防重复行）
        table = _get_lance_table()
        import numpy as np

        records = [
            {
                "chunk_id": str(r.id),
                "content": r.content,
                "collection_id": str(r.collection_id),
                "document_id": str(r.document_id),
                "chunk_index": r.chunk_index,
                "status": "indexed",
                "vector": np.asarray(r.embedding, dtype=np.float32).tolist() if r.embedding else None,
            }
            for r in rows
        ]
        table.merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all().execute(records)
        # BM25 增量（全量重建，个人量级快）
        self.store.bm25.rebuild(await self._bm25_corpus())

    async def _bm25_corpus(self) -> list[tuple[str, str, str]]:
        """全量语料 (chunk_id, content, collection_id)：扫全部集合 index.json 的 indexed 文档分块。"""
        corpus: list[tuple[str, str, str]] = []
        for coll_dir in _collection_dirs(self.store):
            cid = coll_dir.name
            index = await self._load_index(uuid.UUID(cid))
            indexed_docs = {
                did for did, d in index["documents"].items()
                if d.get("status") == "indexed" and not d.get("deleted_at")
            }
            for did in index["chunks"]:
                if did not in indexed_docs:
                    continue
                for c in _active_chunk_records(index, did):
                    corpus.append((c["chunk_id"], c["content"], cid))
        return corpus

    async def has_legacy_active_documents(self) -> bool:
        """Whether startup still needs the compatibility BM25 index for v1 documents."""
        for coll_dir in _collection_dirs(self.store):
            collection_id = uuid.UUID(coll_dir.name)
            try:
                manifest = await self.manifests.load(collection_id)
            except Exception as exc:  # noqa: BLE001  recovery reports broken collections separately
                logger.warning(
                    "KB legacy detection skipped collection_id=%s error_type=%s",
                    collection_id,
                    type(exc).__name__,
                )
                continue
            for document in manifest["documents"].values():
                if (
                    document.get("status") == "indexed"
                    and not document.get("deleted_at")
                    and document.get("active_generation") == LEGACY_GENERATION
                ):
                    return True
        return False

    # ---- 混合检索（T7：双通道换源，RRF/rerank/降级链原样）----

    async def semantic_search(
        self, org_id: uuid.UUID, collection_ids: list[uuid.UUID], query_vec: list[float], limit: int = 50
    ) -> list[tuple[uuid.UUID, str, float]]:
        """语义通道：LanceDB cosine 距离升序。返回 (chunk_id, content, distance)。"""
        table = _get_lance_table()
        if table.count_rows() == 0:
            return []
        where = "status = 'indexed'"
        if collection_ids:
            ids = ",".join(f"'{c}'" for c in collection_ids)
            where += f" AND collection_id IN ({ids})"
        hits = table.search(query_vec).metric("cosine").where(where).limit(limit).to_list()
        return [(uuid.UUID(h["chunk_id"]), h["content"], float(h["_distance"])) for h in hits]

    async def bm25_search(
        self, org_id: uuid.UUID, collection_ids: list[uuid.UUID], query: str, limit: int = 50
    ) -> list[tuple[uuid.UUID, str, float]]:
        """BM25 通道：rank_bm25 打分降序。返回 (chunk_id, content, score)。"""
        cids = [str(c) for c in collection_ids] if collection_ids else None
        hits = self.store.bm25.search(query, collection_ids=cids, limit=limit)
        return [(uuid.UUID(cid), text, score) for cid, text, score in hits]

    async def chunk_sources(self, chunk_ids: list[uuid.UUID]) -> dict[str, dict]:
        """chunk → 来源信息（文档名/集合名，检索结果 source 字段）。"""
        if not chunk_ids:
            return {}
        wanted = {str(c) for c in chunk_ids}
        out: dict[str, dict] = {}
        coll_name_by_id = {
            str(c.id): c.name for c in await self.table.list(filter_fn=lambda c: c.deleted_at is None)
        }
        for coll_dir in _collection_dirs(self.store):
            coll_id = coll_dir.name
            index = await self._load_index(uuid.UUID(coll_id))
            doc_by_id = index["documents"]
            for did in index["chunks"]:
                doc = doc_by_id.get(did)
                if doc is None or doc.get("deleted_at") or doc.get("status") == "archived":
                    continue
                for c in _active_chunk_records(index, did):
                    if c["chunk_id"] in wanted:
                        out[c["chunk_id"]] = {
                            "document_id": did,
                            "filename": doc.get("filename", ""),
                            "collection_id": coll_id,
                            "collection_name": coll_name_by_id.get(coll_id, ""),
                        }
        return out

    async def hybrid_search(
        self,
        org_id: uuid.UUID,
        collection_ids: list[uuid.UUID],
        query: str,
        top_k: int = 5,
        hybrid: dict | None = None,
        embedder: EmbeddingService | None = None,
        reranker: RerankService | None = None,
    ) -> list[dict]:
        """双通道 → RRF 融合（k=60）→ Cross-Encoder 精排 → top_k。服务层与 kb_search 工具共用单一来源。

        语义通道故障静默降级 bm25-only；rerank 故障静默降级 RRF 顺序（不击穿检索）。
        """
        if not query.strip():
            return []
        top_k = max(1, min(top_k, 10))
        hybrid = hybrid or {}
        semantic_on = bool(hybrid.get("semantic", 1))
        bm25_on = bool(hybrid.get("bm25", 1))
        if not semantic_on and not bm25_on:
            return []
        scores: dict[uuid.UUID, float] = defaultdict(float)
        texts: dict[uuid.UUID, str] = {}
        if semantic_on:
            try:
                embedder = embedder or EmbeddingService()
                vec = await embedder.embed_query(query)
                for rank, (cid, text, _dist) in enumerate(await self.semantic_search(org_id, collection_ids, vec), 1):
                    scores[cid] += 1 / (_RRF_K + rank)
                    texts.setdefault(cid, text)
            except Exception as exc:  # noqa: BLE001  语义通道故障 → 降级 bm25-only（不击穿检索）
                logger.warning("semantic channel degraded to bm25-only: %s", exc)
        if bm25_on:
            for rank, (cid, text, _ts) in enumerate(await self.bm25_search(org_id, collection_ids, query), 1):
                scores[cid] += 1 / (_RRF_K + rank)
                texts.setdefault(cid, text)
        if not scores:
            return []
        # Manifest visibility is authoritative even while a lexical/vector index is awaiting cleanup.
        sources = await self.chunk_sources(list(scores))
        visible_ids = {uuid.UUID(chunk_id) for chunk_id in sources}
        scores = {chunk_id: score for chunk_id, score in scores.items() if chunk_id in visible_ids}
        texts = {chunk_id: text for chunk_id, text in texts.items() if chunk_id in visible_ids}
        if not scores:
            return []
        # RRF 粗排 → 候选池 → Cross-Encoder 精排 → top_k（候选 ≤ top_k 或 rerank 故障则回退 RRF 顺序）
        candidates = sorted(scores.items(), key=lambda kv: -kv[1])[: _RERANK_CANDIDATES]
        rerank_scores: dict[uuid.UUID, float] = {}
        if len(candidates) > top_k:
            try:
                reranker = reranker or RerankService()
                docs = [texts[cid] for cid, _ in candidates]
                scored = await reranker.rerank(query, docs, top_n=top_k)  # [(原 index, score)] 降序
                ranked = [(candidates[i][0], scores[candidates[i][0]]) for i, _ in scored]
                rerank_scores = {candidates[i][0]: round(s, 4) for i, s in scored}
            except Exception as exc:  # noqa: BLE001  rerank 故障 → 降级 RRF 顺序（不击穿检索）
                logger.warning("rerank degraded to RRF order: %s", exc)
                ranked = candidates[:top_k]
        else:
            ranked = candidates[:top_k]
        return [
            {
                "chunk_id": str(cid),
                "text": texts[cid],
                "score": round(score, 4),
                "rerank_score": rerank_scores.get(cid),
                "source": sources.get(str(cid), {}),
            }
            for cid, score in ranked
        ]
