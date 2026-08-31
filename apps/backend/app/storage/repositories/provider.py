"""Provider 配置数据访问（《02》前端设计 /settings）。文件化：.agent/providers.json。"""

from __future__ import annotations

import uuid

from app.storage.file.store import get_store
from app.storage.models.provider import ProviderConfig


class ProviderRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("providers")

    async def get_by_id(self, provider_id: uuid.UUID) -> ProviderConfig | None:
        row = await self.table.get(provider_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def list_for_org(self, org_id: uuid.UUID) -> list[ProviderConfig]:
        return await self.table.list(
            filter_fn=lambda p: p.deleted_at is None, sort_key=lambda p: p.created_at
        )

    async def get_enabled(self, org_id: uuid.UUID) -> ProviderConfig | None:
        rows = await self.table.list(
            filter_fn=lambda p: p.enabled and p.deleted_at is None, sort_key=lambda p: p.created_at
        )
        return rows[0] if rows else None

    async def create(
        self, *, org_id: uuid.UUID, name: str, website: str | None = None, base_url: str | None = None,
        is_full_url: bool = False, model: str | None = None, api_key: str | None = None,
        enabled: bool = True, capabilities: list[str] | None = None,
    ) -> ProviderConfig:
        row = ProviderConfig(
            org_id=org_id, name=name, website=website, base_url=base_url, is_full_url=is_full_url,
            model=model, api_key=api_key, enabled=enabled, capabilities=list(capabilities or []),
        )
        self.table.register(row)
        return row
