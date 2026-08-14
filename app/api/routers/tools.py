"""工具路由（docs 03 §5.5）。CRUD/启停/测试/搜索；MCP 注册为 M2.5 接缝。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.tools import CreateToolRequest, ToolTestRequest, ToolToggleRequest, UpdateToolRequest
from app.services.serializers import serialize_tool_definition
from app.services.tool import ToolService
from app.storage.models.user import User
from app.tools.registry import get_by_name

router = APIRouter()


@router.get("/tools/search")  # 必须在 /tools/{tool_id} 之前定义，避免被 path 参数吞掉
async def search_tools(
    q: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hits = await ToolService().search(db, user.org_id, q)
    return ok(hits)


@router.get("/tools")
async def list_tools(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    enabled: bool | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await ToolService().list_for_org(db, user.org_id, page, page_size, enabled=enabled)
    return ok(data)


@router.post("/tools")
async def create_tool(
    req: CreateToolRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await ToolService().create(db, user, req)
    return ok(serialize_tool_definition(row))


@router.get("/tools/{tool_id}")
async def get_tool(
    tool_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await ToolService().get_in_org(db, user.org_id, tool_id)
    spec = get_by_name(row.name)
    data = serialize_tool_definition(row)
    data["aci"] = spec.aci() if spec else None  # docs 03：详情含 ACI schema
    return ok(data)


@router.put("/tools/{tool_id}")
async def update_tool(
    tool_id: str,
    req: UpdateToolRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await ToolService().update(db, user, tool_id, req)
    return ok(serialize_tool_definition(row))


@router.patch("/tools/{tool_id}")
async def toggle_tool(
    tool_id: str,
    req: ToolToggleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await ToolService().set_enabled(db, user, tool_id, req.enabled)
    return ok(serialize_tool_definition(row))


@router.delete("/tools/{tool_id}")
async def delete_tool(
    tool_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ToolService().soft_delete(db, user, tool_id)
    return ok()


@router.post("/tools/{tool_id}/test")
async def test_tool(
    tool_id: str,
    req: ToolTestRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await ToolService().test(db, user.org_id, tool_id, req.params)
    return ok(result)
