"""设置路由（《02》前端设计 /settings Provider tab，前端契约 api/provider.ts）。LLM Provider 配置管理。

api_key 只写不读：请求可带 api_key，响应仅 has_key 布尔（永不回传明文）。
模型/供应商切换（2026-08-27）：多配置 + 唯一激活（activate 热切换）+ 纯 OpenAI 格式（裸名 + 请求地址/完整 URL 开关）。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_db, require_admin
from app.api.envelope import ok
from app.services.provider import ProviderService, serialize_provider
from app.services.sandbox import SandboxService
from app.storage.models.user import User

router = APIRouter()


class SandboxPatchRequest(BaseModel):
    mode: str


@router.get("/settings/sandbox")
async def get_sandbox_settings(
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    return ok(await SandboxService().get(db, user))


@router.patch("/settings/sandbox")
async def patch_sandbox_settings(
    req: SandboxPatchRequest,
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    return ok(await SandboxService().set_mode(db, user, req.mode))


class ProviderWriteRequest(BaseModel):
    name: str  # 配置别名（自由文本）
    website: str | None = None  # 官网链接（可选，纯展示）
    base_url: str | None = None  # 请求地址（base 或完整 URL）
    is_full_url: bool = False  # 请求地址是否完整 URL（含 /chat/completions）
    api_key: str | None = None
    model: str | None = None  # 模型名（裸名）
    enabled: bool | None = None
    capabilities: list[str] | None = None  # 模型能力声明（如 ["vision"]；空/缺省=按模型名 pattern 兜底）


class ProviderPatchRequest(BaseModel):
    name: str | None = None
    website: str | None = None
    base_url: str | None = None
    is_full_url: bool | None = None
    model: str | None = None
    enabled: bool | None = None
    api_key: str | None = None
    capabilities: list[str] | None = None


@router.get("/settings/providers")
async def list_providers(
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    return ok(await ProviderService().list(db, user))


@router.get("/settings/providers/active")
async def get_active_provider(
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    row = await ProviderService().get_active(db, user)
    return ok(serialize_provider(row) if row else None)


@router.post("/settings/providers")
async def create_provider(
    req: ProviderWriteRequest,
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    row = await ProviderService().create(
        db, user, name=req.name, website=req.website, base_url=req.base_url,
        is_full_url=req.is_full_url, model=req.model, api_key=req.api_key,
        enabled=req.enabled if req.enabled is not None else True, capabilities=req.capabilities,
    )
    return ok(serialize_provider(row))


@router.patch("/settings/providers/{provider_id}")
async def patch_provider(
    provider_id: uuid.UUID,
    req: ProviderPatchRequest,
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    # 只应用显式传入的字段（含显式 null = 清空）；未传字段不动
    fields = {k: getattr(req, k) for k in req.model_fields_set}
    row = await ProviderService().patch(db, user, provider_id, **fields)
    return ok(serialize_provider(row))


@router.post("/settings/providers/{provider_id}/activate")
async def activate_provider(
    provider_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    row = await ProviderService().activate(db, user, provider_id)
    return ok(serialize_provider(row))


@router.delete("/settings/providers/{provider_id}")
async def delete_provider(
    provider_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: Any = Depends(get_db),
):
    await ProviderService().delete(db, user, provider_id)
    return ok()
