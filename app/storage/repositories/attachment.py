"""附件数据访问（docs 04 §3.7）。软删行；status 状态机。文件化：.agent/attachments.json。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.storage.file.store import get_store
from app.storage.models.attachment import Attachment


class AttachmentRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("attachments")

    async def get(self, user_id: uuid.UUID, attachment_id: uuid.UUID) -> Attachment | None:
        row = await self.table.get(attachment_id)
        if row is None or row.deleted_at is not None or row.user_id != user_id:
            return None
        return row

    async def get_any_org(self, attachment_id: uuid.UUID) -> Attachment | None:
        """后台分析链全量直查（无请求上下文；权限在服务层校验）。"""
        row = await self.table.get(attachment_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

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
        self.table.register(row)
        return row

    async def soft_delete(self, row: Attachment) -> None:
        row.deleted_at = datetime.now(UTC)

    async def backfill_conversation(
        self, attachment_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> None:
        """消息落库后回填归属（原 chat_stream._backfill_attachments 的 update 语句）。"""
        row = await self.table.get(attachment_id)
        if row is not None:
            row.conversation_id = conversation_id
            row.message_id = message_id
