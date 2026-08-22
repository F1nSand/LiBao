"""KB 文档处理链（docs 01 §9.1）。uploaded→chunking→indexing→indexed/failed。

本地单机化：process_document(document_id) 直连 FileStore（无 sessionmaker 参数）；
每个状态迁移前 re-read 行（防并发覆盖，F4 模式）；embedding 失败 → failed + error。
"""

from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.embeddings import EmbeddingService
from app.services.chunker import chunk_text
from app.storage.file.store import get_store
from app.storage.models.kb import KbChunk
from app.storage.repositories.kb import KbRepository

_PROCESSING = {"uploaded", "chunking", "indexing"}


async def process_document(document_id: uuid.UUID, embedder: EmbeddingService | None = None) -> None:
    """处理链：分块 → 向量化 → 插库 → indexed。异常仅当状态仍在处理中置 failed。"""
    embedder = embedder or EmbeddingService()
    store = get_store()
    repo = KbRepository()
    # re-read（后台链无请求上下文，全量直查；org 校验在服务层完成）
    doc = await repo.get_document(uuid.UUID(int=0), document_id)
    if doc is None or doc.status != "uploaded":
        return  # 防并发：非 uploaded 直接放弃
    doc.status = "chunking"
    await _persist_doc(store, repo, doc)

    coll = await repo.get_collection(uuid.UUID(int=0), doc.collection_id)
    if coll is None:
        await _fail(repo, document_id, "集合不存在")
        return
    chunks = chunk_text(doc.content, coll.chunk_size, coll.chunk_overlap)
    if not chunks:
        await _fail(repo, document_id, "文档内容为空，无法分块")
        return
    if len(chunks) > get_settings().kb_max_chunks:
        await _fail(repo, document_id, f"分块数 {len(chunks)} 超过上限 {get_settings().kb_max_chunks}")
        return

    doc.status = "indexing"
    await _persist_doc(store, repo, doc)
    try:
        vecs = await embedder.embed_documents(chunks)
    except Exception as exc:  # noqa: BLE001  embedding 失败（含 key 缺失）→ failed
        await _fail(repo, document_id, f"向量化失败: {str(exc)[:300]}")
        return
    if len(vecs) != len(chunks):
        await _fail(repo, document_id, "向量化返回数量不符")
        return

    # C1：插库段包 try——存储错误逃出会让文档永久卡 indexing
    try:
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
        await _persist_doc(store, repo, doc)
    except Exception as exc:  # noqa: BLE001  插库失败 → 置 failed
        await _fail(repo, document_id, f"索引落库失败: {str(exc)[:300]}")


async def _persist_doc(store, repo: KbRepository, doc) -> None:
    """文档状态变更落盘（index.json 内嵌 documents 更新）。"""
    index = await repo._load_index(doc.collection_id)  # noqa: SLF001  同模块内部方法
    index["documents"][str(doc.id)] = doc.to_dict()
    await repo._save_index(doc.collection_id, index)  # noqa: SLF001


async def _fail(repo: KbRepository, document_id: uuid.UUID, error: str) -> None:
    """置 failed：仅当状态仍在处理中，不覆盖 archived/indexed 等新状态。"""
    doc = await repo.get_document(uuid.UUID(int=0), document_id)
    if doc is None or doc.status not in _PROCESSING:
        return
    doc.status = "failed"
    doc.error = error[:500]
    await _persist_doc(get_store(), repo, doc)
