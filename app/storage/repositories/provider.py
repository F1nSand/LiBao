"""Provider 配置数据访问（docs 02 /settings）。org 隔离 + 软删。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.provider import ProviderConfig


class ProviderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, provider_id: uuid.UUID) -> ProviderConfig | None:
        return await self.session.get(ProviderConfig, provider_id)

    async def list_for_org(self, org_id: uuid.UUID) -> list[ProviderConfig]:
        stmt = (
            select(ProviderConfig)
            .where(ProviderConfig.org_id == org_id, ProviderConfig.deleted_at.is_(None))
            .order_by(ProviderConfig.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_enabled(self, org_id: uuid.UUID) -> ProviderConfig | None:
        stmt = (
            select(ProviderConfig)
            .where(
                ProviderConfig.org_id == org_id,
                ProviderConfig.enabled.is_(True),
                ProviderConfig.deleted_at.is_(None),
            )
            .order_by(ProviderConfig.created_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def create(
        self, *, org_id: uuid.UUID, name: str, base_url: str | None, model: str | None,
        api_key: str | None, enabled: bool,
    ) -> ProviderConfig:
        row = ProviderConfig(
            org_id=org_id, name=name, base_url=base_url, model=model, api_key=api_key, enabled=enabled
        )
        self.session.add(row)
        return row
