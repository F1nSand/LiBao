"""Provider 配置领域服务（docs 02 /settings Provider tab）。

安全约定（前端契约）：api_key 只写不读——响应仅 has_key 布尔；明文只存库供同步到 LLM 客户端。
激活语义（2026-08-27）：多配置 + 唯一激活——activate 把目标置 enabled、其余置 disabled，并热同步到 Settings。
纯 OpenAI 协议：model 裸名、base_url 归一化为 OpenAI base（resolve_openai_base_url）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.core.errors import ERR_PROVIDER_NOT_FOUND, AppError
from app.core.llm import resolve_openai_base_url
from app.storage.models.provider import ProviderConfig
from app.storage.models.user import User
from app.storage.repositories.provider import ProviderRepository

# patch 允许更新的业务字段（PATCH 显式传 null = 清空；未传 = 不动）
_PATCHABLE_FIELDS = ("name", "website", "base_url", "is_full_url", "model", "api_key", "enabled")


def serialize_provider(p: ProviderConfig) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "website": p.website,
        "base_url": p.base_url,
        "is_full_url": p.is_full_url,
        "model": p.model,
        "enabled": p.enabled,
        "has_key": bool(p.api_key),  # api_key 永不回传，仅布尔标记
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


class ProviderService:
    async def list(self, db: Any, user: User) -> list[dict[str, Any]]:
        return [serialize_provider(p) for p in await ProviderRepository(db).list_for_org(user.org_id)]

    async def get_active(self, db: Any, user: User) -> ProviderConfig | None:
        """当前激活的 provider（无则 None），供 GET /settings/providers/active。"""
        return await ProviderRepository(db).get_enabled(user.org_id)

    async def create(
        self, db: Any, user: User, *, name: str, website: str | None = None,
        base_url: str | None = None, is_full_url: bool = False, model: str | None = None,
        api_key: str | None = None, enabled: bool = True,
    ) -> ProviderConfig:
        row = await ProviderRepository(db).create(
            org_id=user.org_id, name=name, website=website, base_url=base_url,
            is_full_url=is_full_url, model=model, api_key=api_key, enabled=enabled,
        )
        await db.commit()
        await db.refresh(row)
        return row

    async def patch(self, db: Any, user: User, provider_id: uuid.UUID, **fields: Any) -> ProviderConfig:
        """局部更新：只应用传入的字段（含显式 None = 清空）。路由层用 model_fields_set 过滤「显式传入」。"""
        repo = ProviderRepository(db)
        row = await repo.get_by_id(provider_id)
        if row is None or row.org_id != user.org_id or row.deleted_at is not None:
            raise AppError(ERR_PROVIDER_NOT_FOUND, "Provider 不存在或无权访问")
        for key, val in fields.items():
            if key in _PATCHABLE_FIELDS:
                setattr(row, key, val)
        await db.commit()
        await db.refresh(row)
        return row

    async def activate(self, db: Any, user: User, provider_id: uuid.UUID) -> ProviderConfig:
        """设为当前：唯一激活（其余全停）+ 热同步 Settings（进程内即时生效）。"""
        repo = ProviderRepository(db)
        row = await repo.get_by_id(provider_id)
        if row is None or row.org_id != user.org_id or row.deleted_at is not None:
            raise AppError(ERR_PROVIDER_NOT_FOUND, "Provider 不存在或无权访问")
        for p in await repo.list_for_org(user.org_id):
            p.enabled = p.id == provider_id
        await db.commit()
        await db.refresh(row)
        await self.sync_active_to_settings(db, user.org_id)
        return row

    async def delete(self, db: Any, user: User, provider_id: uuid.UUID) -> None:
        repo = ProviderRepository(db)
        row = await repo.get_by_id(provider_id)
        if row is None or row.org_id != user.org_id or row.deleted_at is not None:
            raise AppError(ERR_PROVIDER_NOT_FOUND, "Provider 不存在或无权访问")
        row.deleted_at = datetime.now(UTC)
        await db.commit()

    async def sync_active_to_settings(self, db: Any | None = None, org_id: uuid.UUID | None = None) -> None:
        """同步：激活 provider → 覆盖 Settings（LLMService 即用激活的 provider）。

        base_url 归一化为 OpenAI base（resolve_openai_base_url）；model 用裸名。
        本地单机化：db/org_id 为兼容参数（文件化后忽略），读 providers.json。
        """
        provider = await ProviderRepository().get_enabled(org_id or uuid.UUID(int=0))
        if provider is None:
            return
        settings = get_settings()
        if provider.base_url:
            settings.llm_base_url = resolve_openai_base_url(provider.base_url, provider.is_full_url)
        if provider.model:
            settings.llm_model = provider.model
        if provider.api_key:
            settings.llm_api_key = provider.api_key
