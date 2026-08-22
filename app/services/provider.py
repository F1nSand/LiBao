"""Provider 配置领域服务（docs 02 /settings Provider tab）。

安全约定（前端契约）：api_key 只写不读——响应仅 has_key 布尔；明文只存库供启动同步到 LLM 客户端。
启动同步：lifespan 把启用 provider 的 base_url/model/api_key 覆盖到 Settings，LLMService 即用配置的 provider。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ERR_PROVIDER_NOT_FOUND, AppError
from app.storage.models.provider import ProviderConfig
from app.storage.models.user import User
from app.storage.repositories.provider import ProviderRepository


def serialize_provider(p: ProviderConfig) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "base_url": p.base_url,
        "model": p.model,
        "enabled": p.enabled,
        "has_key": bool(p.api_key),  # api_key 永不回传，仅布尔标记
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


class ProviderService:
    async def list(self, db: AsyncSession, user: User) -> list[dict[str, Any]]:
        return [serialize_provider(p) for p in await ProviderRepository(db).list_for_org(user.org_id)]

    async def create(
        self, db: AsyncSession, user: User, *, name: str, base_url: str | None, model: str | None,
        api_key: str | None, enabled: bool,
    ) -> ProviderConfig:
        row = await ProviderRepository(db).create(
            org_id=user.org_id, name=name, base_url=base_url, model=model, api_key=api_key, enabled=enabled
        )
        await db.commit()
        await db.refresh(row)
        return row

    async def patch(
        self, db: AsyncSession, user: User, provider_id: uuid.UUID, **fields: Any
    ) -> ProviderConfig:
        repo = ProviderRepository(db)
        row = await repo.get_by_id(provider_id)
        if row is None or row.org_id != user.org_id or row.deleted_at is not None:
            raise AppError(ERR_PROVIDER_NOT_FOUND, "Provider 不存在或无权访问")
        for key in ("base_url", "model", "enabled", "api_key"):
            if key in fields and fields[key] is not None:
                setattr(row, key, fields[key])
        await db.commit()
        await db.refresh(row)
        return row

    async def delete(self, db: AsyncSession, user: User, provider_id: uuid.UUID) -> None:
        repo = ProviderRepository(db)
        row = await repo.get_by_id(provider_id)
        if row is None or row.org_id != user.org_id or row.deleted_at is not None:
            raise AppError(ERR_PROVIDER_NOT_FOUND, "Provider 不存在或无权访问")
        row.deleted_at = datetime.now(UTC)
        await db.commit()

    async def sync_active_to_settings(self, db: AsyncSession | None = None, org_id: uuid.UUID | None = None) -> None:
        """启动同步：启用 provider → 覆盖 Settings（LLMService 即用配置的 provider，docs 02 /settings）。

        本地单机化：db/org_id 为兼容参数（文件化后忽略），读 providers.json。
        """
        provider = await ProviderRepository().get_enabled(org_id or uuid.UUID(int=0))
        if provider is None:
            return
        settings = get_settings()
        if provider.base_url:
            settings.llm_base_url = provider.base_url
        if provider.model:
            settings.llm_model = provider.model
        if provider.api_key:
            settings.llm_api_key = provider.api_key
