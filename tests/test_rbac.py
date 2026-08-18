"""M6-1 RBAC 角色守卫单测（纯单元，无 DB）。require_role 工厂 + require_admin/require_developer。"""
from __future__ import annotations

import uuid

import pytest

from app.api.deps import require_admin, require_developer
from app.core.errors import AppError
from app.storage.models.user import User


def _user(role: str) -> User:
    return User(username=uuid.uuid4().hex[:10], password_hash="h", name="X", role=role, org_id=uuid.uuid4())


async def test_require_admin_rejects_non_admin():
    for role in ("developer", "viewer"):
        with pytest.raises(AppError) as exc:
            await require_admin(user=_user(role))
        assert exc.value.code == 40301


async def test_require_admin_allows_admin_and_returns_user():
    admin = _user("admin")
    got = await require_admin(user=admin)
    assert got is admin  # 返回原 user（handler 参数契约）


async def test_require_developer_rejects_viewer():
    with pytest.raises(AppError) as exc:
        await require_developer(user=_user("viewer"))
    assert exc.value.code == 40301


async def test_require_developer_allows_admin_and_developer():
    for role in ("admin", "developer"):
        u = _user(role)
        assert (await require_developer(user=u)) is u
