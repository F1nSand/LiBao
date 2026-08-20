"""M7-B workspace 服务层测试：建目录、重名 40908、更新、软删 40416。"""
from __future__ import annotations

import os
import uuid

import pytest

from app.api.schemas.workspace import CreateWorkspaceRequest, UpdateWorkspaceRequest
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.services import workspace as ws_module
from app.services.serializers import serialize_workspace
from app.services.workspace import WorkspaceService
from app.storage.db import init_db
from app.storage.models import Org, User
from app.tools.builtin import register_builtin_tools
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def workspace_fixture(tmp_path, monkeypatch):
    # 测试用临时 workspaces_root，避免污染真实 data/workspaces
    monkeypatch.setattr(ws_module, "get_settings", lambda: Settings(workspaces_root=str(tmp_path)))
    register_builtin_tools()
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-ws-{uid}")
        session.add(org)
        await session.flush()
        user = User(
            username=f"ws_{uid}", password_hash=hash_password("x"), name="W", role="admin", org_id=org.id
        )
        session.add(user)
        await session.commit()
    yield sessionmaker, user, tmp_path
    await engine.dispose()


async def test_create_workspace_creates_directory(workspace_fixture):
    sessionmaker, user, tmp = workspace_fixture
    async with sessionmaker() as session:
        row = await WorkspaceService().create(
            session, user, CreateWorkspaceRequest(name="proj-a", description="desc")
        )
        assert serialize_workspace(row)["name"] == "proj-a"
        assert row.root_path == str(tmp / str(row.id))
        assert os.path.isdir(row.root_path)  # 真实本地目录已建


async def test_create_duplicate_name_conflict(workspace_fixture):
    sessionmaker, user, _ = workspace_fixture
    async with sessionmaker() as session:
        await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="dup"))
        with pytest.raises(AppError) as exc:
            await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="dup"))
        assert exc.value.code == 40908


async def test_update_workspace(workspace_fixture):
    sessionmaker, user, _ = workspace_fixture
    async with sessionmaker() as session:
        row = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="a"))
        updated = await WorkspaceService().update(
            session, user, str(row.id), UpdateWorkspaceRequest(description="new", system_prompt_fragment="你是项目助手")
        )
        assert updated.description == "new"
        assert updated.system_prompt_fragment == "你是项目助手"


async def test_soft_delete(workspace_fixture):
    sessionmaker, user, _ = workspace_fixture
    async with sessionmaker() as session:
        row = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="gone"))
        await WorkspaceService().soft_delete(session, user, str(row.id))
        with pytest.raises(AppError) as exc:
            await WorkspaceService().get_in_org(session, user.org_id, str(row.id))
        assert exc.value.code == 40416
