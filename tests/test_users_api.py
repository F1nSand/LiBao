"""2e 用户管理测试（DB-backed）：admin CRUD、非 admin 403、重名 40001。"""
from __future__ import annotations

import uuid

import pytest

from app.api.routers.users import _require_admin
from app.core.errors import AppError
from app.core.security import hash_password
from app.services.user import UserService
from app.storage.db import init_db
from app.storage.models import Org, User
from tests.conftest import requires_db

pytestmark = requires_db


def test_require_admin_forbids_non_admin():
    dev = User(username="d", password_hash="h", name="D", role="developer", org_id=uuid.uuid4())
    with pytest.raises(AppError) as exc:
        _require_admin(dev)
    assert exc.value.code == 40301
    admin = User(username="a", password_hash="h", name="A", role="admin", org_id=uuid.uuid4())
    _require_admin(admin)  # 不抛


@pytest.fixture
async def user_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
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
    async with sessionmaker() as session:
        created = await svc.create_user(
            session, username="newbie", password="p", name="新用户", role="viewer", org_id=org.id
        )
        assert created.username == "newbie" and created.role == "viewer" and created.enabled is True
    async with sessionmaker() as session:
        data = await svc.list_paged(session, 1, 20)
        usernames = {u["username"] for u in data["items"]}
        assert {"admin", "dev", "newbie"}.issubset(usernames)
        assert data["total"] == 3


async def test_create_duplicate_username_40001(user_fixture):
    sessionmaker, org, admin, dev = user_fixture
    svc = UserService()
    async with sessionmaker() as session:
        with pytest.raises(AppError) as exc:
            await svc.create_user(
                session, username=admin.username, password="p", name="x", role="viewer", org_id=org.id
            )
        assert exc.value.code == 40001


async def test_change_role_and_status_and_delete(user_fixture):
    sessionmaker, org, admin, dev = user_fixture
    svc = UserService()
    async with sessionmaker() as session:
        updated = await svc.change_role(session, dev.id, "viewer")
        assert updated.role == "viewer"
        disabled = await svc.change_enabled(session, dev.id, False)
        assert disabled.enabled is False
        await svc.soft_delete(session, dev.id)
    async with sessionmaker() as session:
        with pytest.raises(AppError) as exc:
            await svc.get_owned(session, dev.id)  # 软删后不可见
        assert exc.value.code == 40411
