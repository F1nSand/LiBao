"""知识库路由（docs 03 §5.6）。集合/文档 CRUD + 检索。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_developer
from app.api.envelope import ok
from app.api.schemas.kb import CreateCollectionRequest, KbSearchRequest, KbStatusRequest
from app.core.errors import ERR_DOCUMENT_TYPE_UNSUPPORTED, AppError
from app.services.kb import KbService
from app.services.serializers import kb_document_progress, serialize_kb_collection, serialize_kb_document
from app.storage.models.user import User

router = APIRouter()


def _decode_text(data: bytes) -> str:
    """KB 文本提取（严格 UTF-8）。非法 → 40012（S3：客户端内容错误，非 50001）。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AppError(ERR_DOCUMENT_TYPE_UNSUPPORTED, f"文件不是有效的 UTF-8 文本: {exc}") from exc


@router.get("/kb/collections")
async def list_collections(
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    svc = KbService()
    rows = await svc.list_collections(db, user)
    counts = await svc.document_counts(db, user, [c.id for c in rows])
    return ok([serialize_kb_collection(c, counts.get(c.id, 0)) for c in rows])


@router.post("/kb/collections")
async def create_collection(
    req: CreateCollectionRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    coll = await KbService().create_collection(db, user, req.name, req.chunk_size, req.overlap, req.description)
    return ok(serialize_kb_collection(coll, 0))


@router.delete("/kb/collections/{collection_id}")
async def delete_collection(
    collection_id: uuid.UUID,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    await KbService().delete_collection(db, user, collection_id)
    return ok()


@router.get("/kb/collections/{collection_id}/documents")
async def list_documents(
    collection_id: uuid.UUID,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    svc = KbService()
    await svc.get_collection(db, user, collection_id)
    rows = await svc.list_docs(db, collection_id)
    return ok([serialize_kb_document(d) for d in rows])


@router.post("/kb/collections/{collection_id}/documents")
async def upload_document(
    collection_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    """multipart 上传：txt/md 提取文本入库 → uploaded → 后台处理链。"""
    svc = KbService()
    data = await file.read()
    content = _decode_text(data)
    doc = await svc.upload_document(
        db, user, collection_id, filename=file.filename or "untitled",
        content=content, content_type=file.content_type or "text/plain", size_bytes=len(data),
    )
    return ok(serialize_kb_document(doc))


@router.get("/kb/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    doc = await KbService().get_document(db, user, document_id)
    return ok(serialize_kb_document(doc))


@router.get("/kb/documents/{document_id}/status")
async def get_document_status(
    document_id: uuid.UUID,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    doc = await KbService().get_document(db, user, document_id)
    return ok(
        {
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "progress": kb_document_progress(doc.status),
            "error": doc.error,
        }
    )


@router.post("/kb/documents/{document_id}/reindex")
async def reindex_document(
    document_id: uuid.UUID,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    await KbService().reindex_document(db, user, document_id)
    return ok()


@router.patch("/kb/documents/{document_id}/status")
async def patch_document_status(
    document_id: uuid.UUID,
    req: KbStatusRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    await KbService().archive_document(db, user, document_id, req.status)
    return ok()


@router.delete("/kb/documents/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    await KbService().delete_document(db, user, document_id)
    return ok()


@router.post("/kb/search")
async def search_kb(
    req: KbSearchRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    hits = await KbService().search(db, user, req.collection_ids, req.query, req.top_k, req.hybrid)
    return ok(hits)
