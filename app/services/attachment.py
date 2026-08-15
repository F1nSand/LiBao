"""附件领域服务（docs 01 §7.6 / docs 03 §5.9）。本地磁盘存储 MVP（MinIO 为 M4 接缝）。

状态机：uploaded → analyzing → ready | failed（前端 2.5s 轮询 /attachments/{id}/analysis）。
分析链：图片 → ready + 视觉降级文本（I2，无 VLM）；txt/md → utf-8 提取；pdf/office → 仅 metadata。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    ERR_ATTACH_ANALYSIS_FAILURE,
    ERR_ATTACH_STORAGE_FAILURE,
    ERR_ATTACH_TYPE_UNSUPPORTED,
    ERR_ATTACHMENT_NOT_FOUND,
    ERR_FILE_TOO_LARGE,
    AppError,
)
from app.storage.models.attachment import Attachment
from app.storage.models.user import User
from app.storage.repositories.attachment import AttachmentRepository

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_TEXT_TYPES = {"text/plain", "text/markdown"}
_METADATA_ONLY_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ALLOWED = _IMAGE_TYPES | _TEXT_TYPES | _METADATA_ONLY_TYPES
_TEXT_MAX = 2000  # 提取文本截断
_PROCESSING = {"uploaded", "analyzing"}


class AttachmentService:
    async def save_upload(
        self,
        db: AsyncSession,
        user: User,
        filename: str,
        content_type: str,
        data: bytes,
        conversation_id: uuid.UUID | None = None,
    ) -> Attachment:
        """校验（40012/40011）→ 落盘 {upload_dir}/{attachment_id} → uploaded → 触发分析链。"""
        if content_type not in _ALLOWED:
            raise AppError(ERR_ATTACH_TYPE_UNSUPPORTED, f"附件类型不支持: {content_type}")
        if len(data) > get_settings().max_upload_mb * 1024 * 1024:
            raise AppError(ERR_FILE_TOO_LARGE, f"文件超过 {get_settings().max_upload_mb}MB 限制")
        row = await AttachmentRepository(db).create(
            user_id=user.id, filename=filename, content_type=content_type, size_bytes=len(data), storage_path=""
        )
        await db.flush()
        path = Path(get_settings().upload_dir) / str(row.id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            raise AppError(ERR_ATTACH_STORAGE_FAILURE, f"附件存储失败: {exc}") from exc
        row.storage_path = str(path)
        row.conversation_id = conversation_id
        await db.commit()
        await db.refresh(row)
        _spawn_analyze(row.id)
        return row

    async def get_attachment(self, db: AsyncSession, user: User, attachment_id: uuid.UUID) -> Attachment:
        row = await AttachmentRepository(db).get(user.id, attachment_id)
        if row is None:
            raise AppError(ERR_ATTACHMENT_NOT_FOUND, "附件不存在或无权访问")
        return row

    async def read_file(self, att: Attachment) -> bytes:
        try:
            return Path(att.storage_path).read_bytes()
        except OSError as exc:
            raise AppError(ERR_ATTACH_STORAGE_FAILURE, f"附件读取失败: {exc}") from exc

    async def get_analysis(self, db: AsyncSession, user: User, attachment_id: uuid.UUID) -> dict:
        att = await self.get_attachment(db, user, attachment_id)
        if att.status == "failed":
            raise AppError(ERR_ATTACH_ANALYSIS_FAILURE, att.error or "附件分析失败")
        return {
            "attachment_id": str(att.id),
            "summary": (att.analysis or {}).get("text"),
            "extracted_text": (att.analysis or {}).get("text"),
            "status": att.status,
            "error": att.error,
        }

    async def soft_delete(self, db: AsyncSession, user: User, attachment_id: uuid.UUID) -> None:
        att = await self.get_attachment(db, user, attachment_id)
        await AttachmentRepository(db).soft_delete(att)
        await db.commit()
        # 删磁盘文件（尽力而为；路径含 uuid 无引用风险）
        try:
            Path(att.storage_path).unlink(missing_ok=True)
        except OSError:
            pass


async def analyze_attachment(sessionmaker, attachment_id: uuid.UUID) -> None:
    """分析链：uploaded→analyzing→ready|failed。re-read 防并发（F4 模式）。"""
    async with sessionmaker() as db:
        repo = AttachmentRepository(db)
        att = await repo.get_any_org(attachment_id)
        if att is None or att.status != "uploaded":
            return
        att.status = "analyzing"
        await db.commit()
        try:
            analysis = _analyze_content(att)
            att.analysis = analysis
            att.status = "ready"
            att.error = None
        except Exception as exc:  # noqa: BLE001  分析失败 → failed + error（前端降级"无法分析"）
            att.status = "failed"
            att.error = str(exc)[:500]
        await db.commit()


def _analyze_content(att: Attachment) -> dict:
    """按类型分析。图片 → 视觉降级（I2）；文本 → 提取；pdf/office → 仅 metadata。"""
    ct = att.content_type
    if ct in _IMAGE_TYPES:
        return {
            "type": "image",
            "text": "无法分析: 当前部署无视觉模型（VLM 为 M4 接缝）",
            "reason": "no_vision_model",
        }
    if ct in _TEXT_TYPES:
        try:
            text = Path(att.storage_path).read_bytes().decode("utf-8")[: _TEXT_MAX]
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"文本提取失败: {exc}") from exc
        return {"type": "document", "text": text}
    # pdf / office：仅元数据（文本提取为 M4 接缝）
    return {
        "type": "document",
        "text": None,
        "summary": {"filename": att.filename, "size": att.size_bytes},
        "reason": "PDF/Office 文本提取为 M4 接缝",
    }


def _spawn_analyze(attachment_id: uuid.UUID) -> None:
    """经桥触发后台分析链（桥未设时静默：停留 uploaded，轮询可见）。"""
    from app.storage.db import get_sessionmaker

    sessionmaker = get_sessionmaker()
    if sessionmaker is not None:
        asyncio.create_task(analyze_attachment(sessionmaker, attachment_id))
