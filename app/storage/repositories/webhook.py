"""Webhook 配置数据访问（docs 03 §5.10 OC6）。org 隔离 + 软删。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.webhook import WebhookConfig


class WebhookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_org_tool(self, org_id: uuid.UUID, tool_id: str) -> WebhookConfig | None:
        stmt = (
            select(WebhookConfig)
            .where(
                WebhookConfig.org_id == org_id,
                WebhookConfig.tool_id == tool_id,
                WebhookConfig.deleted_at.is_(None),
            )
            .order_by(WebhookConfig.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_tool(self, tool_id: str) -> WebhookConfig | None:
        """公开接收端点按 tool_id 查（registry 工具 id 全局唯一；多 org 同名取最新启用）。"""
        stmt = (
            select(WebhookConfig)
            .where(WebhookConfig.tool_id == tool_id, WebhookConfig.deleted_at.is_(None))
            .order_by(WebhookConfig.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_org(self, org_id: uuid.UUID) -> list[WebhookConfig]:
        stmt = (
            select(WebhookConfig)
            .where(WebhookConfig.org_id == org_id, WebhookConfig.deleted_at.is_(None))
            .order_by(WebhookConfig.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def create(
        self, *, org_id: uuid.UUID, tool_id: str, conversation_id: uuid.UUID | None, token_hash: str
    ) -> WebhookConfig:
        row = WebhookConfig(
            org_id=org_id, tool_id=tool_id, conversation_id=conversation_id, token_hash=token_hash, enabled=True
        )
        self.session.add(row)
        return row
