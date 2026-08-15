"""KB 文档处理链（docs 01 §9.1）。uploaded→chunking→indexing→indexed/failed。

独立 session；每个状态迁移前 re-read 行（防并发覆盖，F4 模式）；embedding 失败 → failed + error。
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.embeddings import EmbeddingService
from app.services.chunker import chunk_text
from app.storage.models.kb import KbChunk
from app.storage.repositories.kb import KbRepository

_PROCESSING = {"uploaded", "chunking", "indexing"}


async def process_document(sessionmaker, document_id: uuid.UUID, embedder: EmbeddingService | None = None) -> None:
    """处理链：分块 → 向量化 → 插库 → indexed。异常仅当状态仍在处理中置 failed。"""
    embedder = embedder or EmbeddingService()
    async with sessionmaker() as db:
        repo = KbRepository(db)
        # re-read（后台链无请求上下文，全 org 直查；org 校验在服务层完成）
        doc = await _get_doc_any_org(db, document_id)
        if doc is None or doc.status != "uploaded":
            return  # 防并发：非 uploaded 直接放弃
        doc.status = "chunking"
        await db.commit()

        coll = await repo.get_collection(doc.org_id, doc.collection_id)
        if coll is None:
            await _fail(db, document_id, "集合不存在")
            return
        chunks = chunk_text(doc.content, coll.chunk_size, coll.chunk_overlap)
        if not chunks:
            await _fail(db, document_id, "文档内容为空，无法分块")
            return
        if len(chunks) > get_settings().kb_max_chunks:
            await _fail(db, document_id, f"分块数 {len(chunks)} 超过上限 {get_settings().kb_max_chunks}")
            return

        doc.status = "indexing"
        await db.commit()
        try:
            vecs = await embedder.embed_documents(chunks)
        except Exception as exc:  # noqa: BLE001  embedding 失败（含 key 缺失）→ failed
            await _fail(db, document_id, f"向量化失败: {str(exc)[:300]}")
            return
        if len(vecs) != len(chunks):
            await _fail(db, document_id, "向量化返回数量不符")
            return

        await repo.delete_chunks(document_id)  # 幂等：reindex 前先清旧
        rows = [
            KbChunk(
                document_id=doc.id,
                collection_id=doc.collection_id,
                org_id=doc.org_id,
                chunk_index=i,
                content=text,
                embedding=vecs[i],
            )
            for i, text in enumerate(chunks)
        ]
        await repo.insert_chunks(rows)
        doc.chunk_count = len(rows)
        doc.status = "indexed"
        doc.error = None
        await db.commit()


async def _get_doc_any_org(db: AsyncSession, document_id: uuid.UUID):
    """全 org 直查（后台链无请求上下文；org 校验在服务层完成）。"""
    from sqlalchemy import select

    from app.storage.models.kb import KbDocument

    stmt = select(KbDocument).where(KbDocument.id == document_id, KbDocument.deleted_at.is_(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def _fail(db: AsyncSession, document_id: uuid.UUID, error: str) -> None:
    """置 failed：re-read 行，仅当仍在处理中（不覆盖 archived/indexed 等新状态）。"""
    doc = await _get_doc_any_org(db, document_id)
    if doc is not None and doc.status in _PROCESSING:
        doc.status = "failed"
        doc.error = error[:500]
        await db.commit()
