"""设置路由（docs 02 /settings Provider tab，前端契约 api/provider.ts）。LLM Provider 配置管理。

api_key 只写不读：请求可带 api_key，响应仅 has_key 布尔（永不回传明文）。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_db, require_admin
from app.api.envelope import ok
from app.services.provider import ProviderService, serialize_provider
from app.storage.models.user import User

router = APIRouter()


class ProviderWriteRequest(BaseModel):
    name: str
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    enabled: bool | None = None


class ProviderPatchRequest(BaseModel):
    base_url: str | None = None
    model: str | None = None
    enabled: bool | None = None
    api_key: str | None = None


@router.get("/settings/providers")
async def list_providers(
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    return ok(await ProviderService().list(db, user))


@router.post("/settings/providers")
async def create_provider(
    req: ProviderWriteRequest,
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    row = await ProviderService().create(
        db, user, name=req.name, base_url=req.base_url, model=req.model,
        api_key=req.api_key, enabled=req.enabled if req.enabled is not None else True,
    )
    return ok(serialize_provider(row))


@router.patch("/settings/providers/{provider_id}")
async def patch_provider(
    provider_id: uuid.UUID,
    req: ProviderPatchRequest,
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    row = await ProviderService().patch(
        db, user, provider_id,
        base_url=req.base_url, model=req.model, enabled=req.enabled, api_key=req.api_key,
    )
    return ok(serialize_provider(row))


@router.delete("/settings/providers/{provider_id}")
async def delete_provider(
    provider_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    await ProviderService().delete(db, user, provider_id)
    return ok()
