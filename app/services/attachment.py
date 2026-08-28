"""附件领域服务（docs 01 §7.6 / docs 03 §5.9）。本地磁盘存储 MVP（MinIO 为 M4 接缝）。

状态机：uploaded → analyzing → ready | failed（内部抽取缓存；不表示模型已读取）。
分析链：图片保留 vision 兼容诊断；txt/md → utf-8 提取；pdf/docx → 正文抽取；legacy .doc 拒绝上传。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import (
    ERR_ATTACH_ANALYSIS_FAILURE,
    ERR_ATTACH_STORAGE_FAILURE,
    ERR_ATTACH_TYPE_UNSUPPORTED,
    ERR_ATTACHMENT_NOT_FOUND,
    ERR_FILE_TOO_LARGE,
    AppError,
)
from app.storage.attachment_analysis import (
    _ALLOWED,
    _IMAGE_TYPES,
    EXTRACTION_STRATEGY,
    EXTRACTOR_VERSION,
    analyze_content,
)
from app.storage.file.store import get_store
from app.storage.models.attachment import Attachment
from app.storage.models.user import User
from app.storage.repositories.attachment import AttachmentRepository


class AttachmentService:
    async def save_upload(
        self,
        db: Any,
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

    async def get_attachment(self, db: Any, user: User, attachment_id: uuid.UUID) -> Attachment:
        row = await AttachmentRepository(db).get(user.id, attachment_id)
        if row is None:
            raise AppError(ERR_ATTACHMENT_NOT_FOUND, "附件不存在或无权访问")
        return row

    async def get_owned_many(
        self, db: Any, user_id: uuid.UUID, attachment_ids: list[uuid.UUID]
    ) -> list[Attachment]:
        """按请求顺序批量校验归属；任何缺失、软删或他人附件都统一报 40403。"""
        repo = AttachmentRepository(db)
        rows: list[Attachment] = []
        for attachment_id in attachment_ids:
            row = await repo.get(user_id, attachment_id)
            if row is None:
                raise AppError(ERR_ATTACHMENT_NOT_FOUND, "附件不存在或无权访问")
            rows.append(row)
        return rows

    async def get_attachment_by_id(self, db: Any, attachment_id: uuid.UUID) -> Attachment | None:
        """按 id 直取（不做 owner 校验）——编排层专用：owner 校验已在 chat 路由唯一入口完成（项目既有约定）。"""
        return await AttachmentRepository(db).get_any_org(attachment_id)

    async def read_file(self, att: Attachment) -> bytes:
        try:
            return Path(att.storage_path).read_bytes()
        except OSError as exc:
            raise AppError(ERR_ATTACH_STORAGE_FAILURE, f"附件读取失败: {exc}") from exc

    async def ensure_extracted(self, db: Any, att: Attachment) -> dict[str, Any]:
        """确保文档正文抽取缓存可用；聊天消费和上传后台预热共用此状态。

        ``ready`` 只代表抽取缓存完成，不代表模型已经读过文件。图片不走此方法，
        仍由 vision 流程按当前模型能力读取原始字节。
        """
        if (
            att.status == "ready"
            and isinstance(att.analysis, dict)
            and att.analysis.get("extractor_version") == EXTRACTOR_VERSION
            and att.analysis.get("extraction_strategy") == EXTRACTION_STRATEGY
        ):
            return att.analysis
        att.status = "analyzing"
        await db.commit()
        try:
            analysis = await asyncio.to_thread(analyze_content, att)
            att.analysis = analysis
            if analysis.get("text") is None and att.content_type not in _IMAGE_TYPES:
                att.status = "failed"
                att.error = analysis.get("reason") or "文档正文提取失败"
            else:
                att.status = "ready"
                att.error = None
        except Exception as exc:  # noqa: BLE001
            att.analysis = None
            att.status = "failed"
            att.error = str(exc)[:500]
        await db.commit()
        return att.analysis or {"type": "document", "text": None, "reason": att.error or "文档正文提取失败"}

    async def get_analysis(self, db: Any, user: User, attachment_id: uuid.UUID) -> dict:
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

    async def soft_delete(self, db: Any, user: User, attachment_id: uuid.UUID) -> None:
        att = await self.get_attachment(db, user, attachment_id)
        await AttachmentRepository(db).soft_delete(att)
        await db.commit()
        # 删磁盘文件（尽力而为；路径含 uuid 无引用风险）
        try:
            Path(att.storage_path).unlink(missing_ok=True)
        except OSError:
            pass


async def analyze_attachment(attachment_id: uuid.UUID) -> None:
    """分析链：uploaded→analyzing→ready|failed。re-read 防并发（F4 模式）。"""
    async with get_store().session() as db:
        repo = AttachmentRepository(db)
        att = await repo.get_any_org(attachment_id)
        if att is None or att.status != "uploaded":
            return
        service = AttachmentService()
        await service.ensure_extracted(db, att)


def _spawn_analyze(attachment_id: uuid.UUID) -> None:
    """触发后台分析链（本地单机化：直连 store）。"""
    from app.core.async_utils import spawn_background

    spawn_background(analyze_attachment, attachment_id)
