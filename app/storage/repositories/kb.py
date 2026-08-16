"""知识库数据访问（docs 04 §3.6）。集合/文档软删；分块硬删重建（派生数据）。"""
from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import EmbeddingService
from app.storage.models.kb import KbChunk, KbCollection, KbDocument

logger = logging.getLogger(__name__)

_CJK = re.compile(r"([一-鿿])")
_RRF_K = 60  # 倒数排名融合常数（docs 01 §9.1）


def space_cjk(text: str) -> str:
    """CJK 逐字插空格（与迁移 0004 GENERATED tsvector 表达式一致——BM25 查询侧同一变换）。"""
    return _CJK.sub(r"\1 ", text)


class KbRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- 集合 ----

    async def get_collection(self, org_id: uuid.UUID, collection_id: uuid.UUID) -> KbCollection | None:
        stmt = select(KbCollection).where(
            KbCollection.org_id == org_id,
            KbCollection.id == collection_id,
            KbCollection.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        stmt = select(KbCollection.id).where(
            KbCollection.org_id == org_id,
            KbCollection.name == name,
            KbCollection.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).first() is not None

    async def document_counts(
        self, org_id: uuid.UUID, collection_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """各集合非软删文档数（单条 GROUP BY，供集合列表 document_count；S11）。"""
        if not collection_ids:
            return {}
        stmt = (
            select(KbDocument.collection_id, func.count())
            .where(
                KbDocument.org_id == org_id,
                KbDocument.deleted_at.is_(None),
                KbDocument.collection_id.in_(collection_ids),
            )
            .group_by(KbDocument.collection_id)
        )
        return {cid: int(n) for cid, n in (await self.session.execute(stmt)).all()}

    async def list_collections(self, org_id: uuid.UUID) -> list[KbCollection]:
        stmt = (
            select(KbCollection)
            .where(KbCollection.org_id == org_id, KbCollection.deleted_at.is_(None))
            .order_by(KbCollection.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def create_collection(
        self, org_id: uuid.UUID, name: str, chunk_size: int, chunk_overlap: int, description: str = ""
    ) -> KbCollection:
        row = KbCollection(
            org_id=org_id, name=name, description=description, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        self.session.add(row)
        return row

    async def soft_delete_collection(self, coll: KbCollection) -> None:
        coll.deleted_at = datetime.now(UTC)
        self.session.add(coll)

    # ---- 文档 ----

    async def get_document(self, org_id: uuid.UUID, document_id: uuid.UUID) -> KbDocument | None:
        stmt = select(KbDocument).where(
            KbDocument.org_id == org_id,
            KbDocument.id == document_id,
            KbDocument.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_documents(self, collection_id: uuid.UUID) -> list[KbDocument]:
        stmt = (
            select(KbDocument)
            .where(KbDocument.collection_id == collection_id, KbDocument.deleted_at.is_(None))
            .order_by(KbDocument.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

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
        self.session.add(row)
        return row

    async def soft_delete_document(self, doc: KbDocument) -> None:
        doc.deleted_at = datetime.now(UTC)
        self.session.add(doc)

    async def delete_chunks(self, document_id: uuid.UUID) -> None:
        await self.session.execute(delete(KbChunk).where(KbChunk.document_id == document_id))

    async def delete_collection_chunks(self, collection_id: uuid.UUID) -> None:
        await self.session.execute(delete(KbChunk).where(KbChunk.collection_id == collection_id))

    # ---- 分块 ----

    async def list_chunks(self, document_id: uuid.UUID) -> list[KbChunk]:
        stmt = (
            select(KbChunk)
            .where(KbChunk.document_id == document_id)
            .order_by(KbChunk.chunk_index.asc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def insert_chunks(self, rows: list[KbChunk]) -> None:
        self.session.add_all(rows)

    async def count_chunks(self, document_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(KbChunk).where(KbChunk.document_id == document_id)
        return int((await self.session.execute(stmt)).scalar_one())

    # ---- 混合检索（T7）----

    def _indexed_filter(self, org_id: uuid.UUID, collection_ids: list[uuid.UUID]):
        stmt = select(KbChunk.id, KbChunk.content).join(KbDocument, KbDocument.id == KbChunk.document_id).where(
            KbChunk.org_id == org_id,
            KbDocument.status == "indexed",
            KbDocument.deleted_at.is_(None),
        )
        if collection_ids:
            stmt = stmt.where(KbChunk.collection_id.in_(collection_ids))
        return stmt

    async def semantic_search(
        self, org_id: uuid.UUID, collection_ids: list[uuid.UUID], query_vec: list[float], limit: int = 50
    ) -> list[tuple[uuid.UUID, str, float]]:
        """语义通道：余弦距离升序（HNSW）。返回 (chunk_id, content, distance)。"""
        stmt = self._indexed_filter(org_id, collection_ids)
        stmt = stmt.add_columns(KbChunk.embedding.cosine_distance(query_vec).label("dist"))
        stmt = stmt.order_by("dist").limit(limit)
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], float(r[2])) for r in rows]

    async def bm25_search(
        self, org_id: uuid.UUID, collection_ids: list[uuid.UUID], query: str, limit: int = 50
    ) -> list[tuple[uuid.UUID, str, float]]:
        """BM25 通道：tsvector @@ plainto_tsquery + ts_rank 降序（GIN）。返回 (chunk_id, content, rank)。"""
        tsq = func.plainto_tsquery("simple", space_cjk(query))
        stmt = self._indexed_filter(org_id, collection_ids)
        stmt = stmt.add_columns(func.ts_rank(KbChunk.content_tsv, tsq).label("rank"))
        stmt = stmt.where(KbChunk.content_tsv.op("@@")(tsq))
        stmt = stmt.order_by(desc("rank")).limit(limit)
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], float(r[2])) for r in rows]

    async def chunk_sources(self, chunk_ids: list[uuid.UUID]) -> dict[str, dict]:
        """chunk → 来源信息（文档名/集合名，检索结果 source 字段）。"""
        if not chunk_ids:
            return {}
        stmt = (
            select(KbChunk.id, KbDocument.filename, KbDocument.id, KbCollection.name, KbCollection.id)
            .join(KbDocument, KbDocument.id == KbChunk.document_id)
            .join(KbCollection, KbCollection.id == KbChunk.collection_id)
            .where(KbChunk.id.in_(chunk_ids))
        )
        out: dict[str, dict] = {}
        for cid, filename, doc_id, coll_name, coll_id in (await self.session.execute(stmt)).all():
            out[str(cid)] = {
                "document_id": str(doc_id),
                "filename": filename,
                "collection_id": str(coll_id),
                "collection_name": coll_name,
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
    ) -> list[dict]:
        """双通道 → RRF 融合（k=60）→ top_k。服务层与 kb_search 工具共用单一来源。

        rerank_score 恒 null（Cross-Encoder 为 M4 接缝）；语义通道故障静默降级 bm25-only。
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
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]
        sources = await self.chunk_sources([cid for cid, _ in ranked])
        return [
            {
                "chunk_id": str(cid),
                "text": texts[cid],
                "score": round(score, 4),
                "rerank_score": None,
                "source": sources.get(str(cid), {}),
            }
            for cid, score in ranked
        ]
