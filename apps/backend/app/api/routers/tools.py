"""工具路由（《02》接口契约 §5.5）。CRUD/启停/测试/搜索 + MCP 源注册/列表/注销（M2.5）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, require_developer
from app.api.envelope import ok
from app.api.schemas.tools import (
    CreateToolRequest,
    McpRegisterRequest,
    ToolTestRequest,
    ToolToggleRequest,
    UpdateToolRequest,
)
from app.services.mcp import McpService
from app.services.serializers import serialize_tool_definition
from app.services.tool import ToolService
from app.storage.models.user import User
from app.tools.registry import get_by_name

router = APIRouter()


@router.get("/tools/search")  # 必须在 /tools/{tool_id} 之前定义，避免被 path 参数吞掉
async def search_tools(
    q: str = Query(..., min_length=1),
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    hits = await ToolService().search(db, user.org_id, q)
    return ok(hits)


# ---- MCP 源（M2.5）：register/list/unregister 同样须在 /tools/{tool_id} 之前 ----

@router.post("/tools/mcp/register")
async def register_mcp(
    req: McpRegisterRequest,
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    return ok(await McpService().register(db, user, req))


@router.get("/tools/mcp")
async def list_mcp_servers(
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    return ok(await McpService().list_servers(db, user.org_id))


@router.delete("/tools/mcp/{server_id}")
async def unregister_mcp(
    server_id: str,
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    await McpService().unregister(db, user, server_id)
    return ok()


@router.get("/tools")
async def list_tools(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    enabled: bool | None = Query(None),
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    data = await ToolService().list_for_org(db, user.org_id, page, page_size, enabled=enabled)
    return ok(data)


@router.post("/tools")
async def create_tool(
    req: CreateToolRequest,
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    row = await ToolService().create(db, user, req)
    return ok(serialize_tool_definition(row))


@router.get("/tools/{tool_id}")
async def get_tool(
    tool_id: str,
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    row = await ToolService().get_in_org(db, user.org_id, tool_id)
    spec = get_by_name(row.name)
    data = serialize_tool_definition(row)
    data["aci"] = spec.aci() if spec else None  # 《02》接口契约：详情含 ACI schema
    return ok(data)


@router.put("/tools/{tool_id}")
async def update_tool(
    tool_id: str,
    req: UpdateToolRequest,
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    row = await ToolService().update(db, user, tool_id, req)
    return ok(serialize_tool_definition(row))


@router.patch("/tools/{tool_id}")
async def toggle_tool(
    tool_id: str,
    req: ToolToggleRequest,
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    row = await ToolService().set_enabled(db, user, tool_id, req.enabled)
    return ok(serialize_tool_definition(row))


@router.delete("/tools/{tool_id}")
async def delete_tool(
    tool_id: str,
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    await ToolService().soft_delete(db, user, tool_id)
    return ok()


@router.post("/tools/{tool_id}/test")
async def test_tool(
    tool_id: str,
    req: ToolTestRequest,
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    result = await ToolService().test(db, user.org_id, tool_id, req.params)
    return ok(result)
