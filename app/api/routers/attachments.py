"""附件路由（docs 03 §5.9）。上传（multipart）/二进制流/分析/删除。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.services.attachment import AttachmentService
from app.services.serializers import serialize_attachment
from app.storage.models.user import User

router = APIRouter()


@router.post("/uploads")
async def upload_attachment(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    att = await AttachmentService().save_upload(
        db, user, file.filename or "untitled", file.content_type or "application/octet-stream", data
    )
    return ok(serialize_attachment(att))


@router.get("/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """附件二进制流（图片预览/下载；FileResponse 带原始文件名）。"""
    svc = AttachmentService()
    att = await svc.get_attachment(db, user, attachment_id)
    return FileResponse(att.storage_path, media_type=att.content_type, filename=att.filename)


@router.get("/attachments/{attachment_id}/analysis")
async def get_attachment_analysis(
    attachment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await AttachmentService().get_analysis(db, user, attachment_id))


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await AttachmentService().soft_delete(db, user, attachment_id)
    return ok()
