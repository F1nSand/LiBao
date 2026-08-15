"""知识库路由（docs 03 §5.6）。集合/文档 CRUD + 检索。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.kb import CreateCollectionRequest, KbStatusRequest
from app.services.kb import KbService
from app.services.serializers import serialize_kb_collection, serialize_kb_document
from app.storage.models.user import User

router = APIRouter()


@router.get("/kb/collections")
async def list_collections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await KbService().list_collections(db, user)
    return ok([serialize_kb_collection(c, 0) for c in rows])


@router.post("/kb/collections")
async def create_collection(
    req: CreateCollectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    coll = await KbService().create_collection(db, user, req.name, req.chunk_size, req.overlap, req.description)
    return ok(serialize_kb_collection(coll, 0))


@router.delete("/kb/collections/{collection_id}")
async def delete_collection(
    collection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await KbService().delete_collection(db, user, collection_id)
    return ok()


@router.get("/kb/collections/{collection_id}/documents")
async def list_documents(
    collection_id: uuid.UUID,
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """multipart 上传：txt/md 提取文本入库 → uploaded → 后台处理链。"""
    svc = KbService()
    data = await file.read()
    try:
        content = data.decode("utf-8")  # 严格模式
    except UnicodeDecodeError as exc:
        raise ValueError(f"文件不是有效的 UTF-8 文本: {exc}") from exc
    doc = await svc.upload_document(
        db, user, collection_id, filename=file.filename or "untitled",
        content=content, content_type=file.content_type or "text/plain", size_bytes=len(data),
    )
    return ok(serialize_kb_document(doc))


@router.get("/kb/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await KbService().get_document(db, user, document_id)
    return ok(serialize_kb_document(doc))


@router.get("/kb/documents/{document_id}/status")
async def get_document_status(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await KbService().get_document(db, user, document_id)
    return ok(
        {"status": doc.status, "chunk_count": doc.chunk_count, "progress": doc.error is not None, "error": doc.error}
    )


@router.post("/kb/documents/{document_id}/reindex")
async def reindex_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await KbService().reindex_document(db, user, document_id)
    return ok()


@router.patch("/kb/documents/{document_id}/status")
async def patch_document_status(
    document_id: uuid.UUID,
    req: KbStatusRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await KbService().archive_document(db, user, document_id, req.status)
    return ok()


@router.delete("/kb/documents/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await KbService().delete_document(db, user, document_id)
    return ok()
