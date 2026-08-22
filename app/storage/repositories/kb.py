"""知识库数据访问（docs 04 §3.6）。集合/文档软删；分块硬删重建（派生数据）。

本地单机化：
- 集合：.agent/kb_collections.json（FileTable）
- 文档+分块：kb/<collection_id>/index.json（documents/chunks 内嵌）+ documents/<doc_id>.md（原文）
- 向量：kb/vectors.lance（LanceDB 单表，chunk_id 主键，merge_insert 增量 upsert）
- BM25：FileStore.bm25（rank_bm25 内存索引，启动/变更后全量重建）

混合检索（hybrid_search）代码原样保留：双通道换源，RRF k=60 + rerank + 降级链不变。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app.core.embeddings import EmbeddingService
from app.core.rerank import RerankService
from app.storage.file.store import get_store
from app.storage.models.kb import KbChunk, KbCollection, KbDocument

logger = logging.getLogger(__name__)

_CJK = re.compile(r"([一-鿿])")
_RRF_K = 60  # 倒数排名融合常数（docs 01 §9.1）
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
        return self.store.kb_root / str(collection_id) / "index.json"

    async def _load_index(self, collection_id: uuid.UUID) -> dict[str, Any]:
        path = self._index_path(collection_id)
        if not path.exists():
            return {"version": 1, "documents": {}, "chunks": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "documents": {}, "chunks": {}}

    async def _save_index(self, collection_id: uuid.UUID, index: dict[str, Any]) -> None:
        path = self._index_path(collection_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            with __import__("contextlib").suppress(OSError):
                os.unlink(tmp)
            raise

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
        index = await self._load_index(collection_id)
        index["documents"][str(row.id)] = row.to_dict()
        await self._save_index(collection_id, index)
        # 原文落盘（目标布局 documents/<doc_id>.md；文档原文即上传文本，小文件同步写可接受）
        md_path = self.store.kb_root / str(collection_id) / "documents" / f"{row.id}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(content, encoding="utf-8")
        return row

    async def soft_delete_document(self, doc: KbDocument) -> None:
        doc.deleted_at = datetime.now(UTC)
        index = await self._load_index(doc.collection_id)
        index["documents"][str(doc.id)]["deleted_at"] = doc.deleted_at.isoformat()
        await self._save_index(doc.collection_id, index)

    async def persist_document(self, doc: KbDocument) -> None:
        """文档状态/字段变更落盘（服务层直接赋值后调用；index.json 不走 FileTable）。"""
        index = await self._load_index(doc.collection_id)
        index["documents"][str(doc.id)] = doc.to_dict()
        await self._save_index(doc.collection_id, index)

    async def delete_chunks(self, document_id: uuid.UUID) -> None:
        """硬删分块（reindex 前清旧 / 文档删除）。"""
        for coll_dir in _collection_dirs(self.store):
            index = await self._load_index(uuid.UUID(coll_dir.name))
            if str(document_id) not in index["chunks"]:
                continue
            cids = [c["chunk_id"] for c in index["chunks"].pop(str(document_id))]
            await self._save_index(uuid.UUID(coll_dir.name), index)
            await self._lance_delete_document(str(document_id), cids)
            self.store.bm25.rebuild(await self._bm25_corpus())
            return

    async def delete_collection_chunks(self, collection_id: uuid.UUID) -> None:
        """集合级分块硬删（集合软删时调用）。"""
        index = await self._load_index(collection_id)
        index["chunks"] = {}
        await self._save_index(collection_id, index)
        _get_lance_table().delete(f"collection_id = '{collection_id}'")
        self.store.bm25.rebuild(await self._bm25_corpus())

    async def _lance_delete_document(self, document_id: str, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        try:
            _get_lance_table().delete(f"document_id = '{document_id}'")
        except Exception as exc:  # noqa: BLE001  表不存在/空表容错
            logger.debug("lance delete skip: %s", exc)

    # ---- 分块 ----

    async def list_chunks(self, document_id: uuid.UUID) -> list[KbChunk]:
        for coll_dir in _collection_dirs(self.store):
            index = await self._load_index(uuid.UUID(coll_dir.name))
            chunks = index["chunks"].get(str(document_id))
            if chunks is not None:
                rows = []
                for c in chunks:
                    row = KbChunk(
                        id=uuid.UUID(c["chunk_id"]),
                        document_id=document_id,
                        collection_id=uuid.UUID(coll_dir.name),
                        org_id=uuid.UUID(int=0),
                        chunk_index=c["chunk_index"],
                        content=c["content"],
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
        index = await self._load_index(collection_id)
        index["chunks"][str(rows[0].document_id)] = [
            {
                "chunk_id": str(r.id),
                "document_id": str(r.document_id),
                "collection_id": str(r.collection_id),
                "chunk_index": r.chunk_index,
                "content": r.content,
            }
            for r in rows
        ]
        await self._save_index(collection_id, index)
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
            for did, chunks in index["chunks"].items():
                if did not in indexed_docs:
                    continue
                for c in chunks:
                    corpus.append((c["chunk_id"], c["content"], cid))
        return corpus

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
            for did, chunks in index["chunks"].items():
                doc = doc_by_id.get(did)
                if doc is None:
                    continue
                for c in chunks:
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
        sources = await self.chunk_sources([cid for cid, _ in ranked])
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
