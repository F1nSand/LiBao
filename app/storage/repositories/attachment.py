"""附件数据访问（docs 04 §3.7）。软删行；status 状态机。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.attachment import Attachment


class AttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID, attachment_id: uuid.UUID) -> Attachment | None:
        stmt = select(Attachment).where(
            Attachment.user_id == user_id,
            Attachment.id == attachment_id,
            Attachment.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_any_org(self, attachment_id: uuid.UUID) -> Attachment | None:
        """后台分析链全量直查（无请求上下文；权限在服务层校验）。"""
        stmt = select(Attachment).where(Attachment.id == attachment_id, Attachment.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
        storage_path: str,
    ) -> Attachment:
        row = Attachment(
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            status="uploaded",
        )
        self.session.add(row)
        return row

    async def soft_delete(self, row: Attachment) -> None:
        row.deleted_at = datetime.now(UTC)
        self.session.add(row)
