"""2e 用户管理测试（DB-backed）：admin CRUD、重名 40001、org 收敛。require_role 守卫单测见 test_rbac.py。"""
from __future__ import annotations

import uuid

import pytest

from app.core.errors import AppError
from app.core.security import hash_password
from app.services.user import UserService
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import Org, User
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def user_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-users-{uid}")
        session.add(org)
        await session.flush()
        admin = User(
            username=f"admin_{uid}", password_hash=hash_password("x"), name="A", role="admin", org_id=org.id
        )
        session.add(admin)
        await session.flush()
        dev = User(
            username=f"dev_{uid}", password_hash=hash_password("x"), name="D", role="developer", org_id=org.id
        )
        session.add(dev)
        await session.commit()
    yield sessionmaker, org, admin, dev
    await engine.dispose()


async def test_admin_create_and_list(user_fixture):
    sessionmaker, org, admin, dev = user_fixture
    svc = UserService()
    username = f"newbie_{uuid.uuid4().hex[:6]}"  # 唯一用户名，避免残留冲突
    async with get_store().session(sessionmaker) as session:
        created = await svc.create_user(
            session, username=username, password="p", name="新用户", role="viewer", org_id=org.id
        )
        assert created.username == username and created.role == "viewer" and created.enabled is True
    async with get_store().session(sessionmaker) as session:
        data = await svc.list_paged(session, 1, 20)
        usernames = {u["username"] for u in data["items"]}
        assert username in usernames
        assert admin.username in usernames and dev.username in usernames
        assert data["total"] >= 3  # 共享 DB：先前测试残留用户，只断言下限


async def test_create_duplicate_username_40001(user_fixture):
    sessionmaker, org, admin, dev = user_fixture
    svc = UserService()
    async with get_store().session(sessionmaker) as session:
        with pytest.raises(AppError) as exc:
            await svc.create_user(
                session, username=admin.username, password="p", name="x", role="viewer", org_id=org.id
            )
        assert exc.value.code == 40906


async def test_change_role_and_status_and_delete(user_fixture):
    sessionmaker, org, admin, dev = user_fixture
    svc = UserService()
    async with get_store().session(sessionmaker) as session:
        updated = await svc.change_role(session, admin, dev.id, "viewer")
        assert updated.role == "viewer"
        disabled = await svc.change_enabled(session, admin, dev.id, False)
        assert disabled.enabled is False
        await svc.soft_delete(session, admin, dev.id)
    async with get_store().session(sessionmaker) as session:
        with pytest.raises(AppError) as exc:
            await svc.get_owned(session, dev.id, org.id)  # 软删后不可见
        assert exc.value.code == 40411


async def _create_org_user(session, prefix: str) -> tuple[Org, User]:
    """建「独立 org + viewer 用户」：跨 org 隔离测试的共享脚手架。"""
    org = Org(name=f"测试组织-{prefix}-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    user = User(
        username=f"{prefix}_{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("x"),
        name=prefix.upper(),
        role="viewer",
        org_id=org.id,
    )
    session.add(user)
    await session.flush()
    return org, user


async def test_admin_cannot_manage_other_org_user(user_fixture):
    """跨 org 管理收紧：他 org 用户对当前 org admin 一律视为不存在（40411，防存在性探测）。"""
    sessionmaker, org, admin, dev = user_fixture
    svc = UserService()
    async with get_store().session(sessionmaker) as session:
        _, other_user = await _create_org_user(session, "other")
        await session.commit()
        other_id = other_user.id
    async with get_store().session(sessionmaker) as session:
        with pytest.raises(AppError) as exc:
            await svc.change_role(session, admin, other_id, "developer")
        assert exc.value.code == 40411


async def test_admin_cannot_manage_self(user_fixture):
    """自身操作守卫：admin 不能自删/自禁/自降权（防最后一个 admin 自锁死）。"""
    sessionmaker, org, admin, dev = user_fixture
    svc = UserService()
    async with get_store().session(sessionmaker) as session:
        with pytest.raises(AppError) as exc:
            await svc.soft_delete(session, admin, admin.id)
        assert exc.value.code == 40301
        with pytest.raises(AppError) as exc:
            await svc.change_enabled(session, admin, admin.id, False)
        assert exc.value.code == 40301
        with pytest.raises(AppError) as exc:
            await svc.change_role(session, admin, admin.id, "viewer")
        assert exc.value.code == 40301


async def test_list_paged_filters_by_org(user_fixture):
    """org_id 过滤：列表只含本组织用户（org A/B 各建，互不可见）。"""
    sessionmaker, org_a, admin, dev = user_fixture
    svc = UserService()
    async with get_store().session(sessionmaker) as session:
        await _create_org_user(session, "orgb")
        await session.commit()
    async with get_store().session(sessionmaker) as session:
        data_a = await svc.list_paged(session, 1, 100, org_id=org_a.id)
        assert all(u["org_id"] == str(org_a.id) for u in data_a["items"])
        assert admin.username in {u["username"] for u in data_a["items"]}
        assert not any(u["username"].startswith("orgb_") for u in data_a["items"])


async def test_list_paged_includes_org_name(user_fixture):
    """M6 收尾：/users 响应带 org_name（前端 org 列可读名称，回退 UUID）。"""
    sessionmaker, org, admin, dev = user_fixture
    svc = UserService()
    async with get_store().session(sessionmaker) as session:
        data = await svc.list_paged(session, 1, 100, org_id=org.id)
        by_username = {u["username"]: u for u in data["items"]}
        assert by_username[admin.username]["org_name"] == org.name
        assert by_username[admin.username]["org_id"] == str(org.id)
        assert "org_name" in by_username[dev.username]  # 所有用户都带 org_name 字段
