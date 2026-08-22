"""M6 前：Provider 配置测试（DB-backed）——CRUD + api_key 只写不读（has_key）+ 启动同步。"""
from __future__ import annotations

import uuid

import pytest

from app.services.provider import ProviderService, serialize_provider
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import Org, User
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def provider_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-pv-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"pv_{uid}", password_hash="hashed", name="P", role="admin", org_id=org.id)
        session.add(user)
        await session.commit()
    yield sessionmaker, user
    await engine.dispose()


async def test_provider_crud_and_api_key_write_only(provider_fixture):
    sessionmaker, user = provider_fixture
    svc = ProviderService()
    async with get_store().session(sessionmaker) as session:
        p = await svc.create(
            session, user, name="deepseek", base_url="https://api.deepseek.com", model="deepseek-chat",
            api_key="sk-secret-123", enabled=True,
        )
        pid = p.id
        listed = await svc.list(session, user)
        assert listed[0]["name"] == "deepseek"
        assert listed[0]["has_key"] is True
        assert "api_key" not in listed[0]  # api_key 永不回传
        assert "sk-secret-123" not in str(listed[0])

        patched = await svc.patch(session, user, pid, enabled=False, model="deepseek-v4-flash")
        assert patched.enabled is False and patched.model == "deepseek-v4-flash"
        assert serialize_provider(patched)["has_key"] is True

        await svc.delete(session, user, pid)
        assert await svc.list(session, user) == []


async def test_provider_sync_active_to_settings(provider_fixture, monkeypatch):
    sessionmaker, user = provider_fixture
    svc = ProviderService()
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "default/model")
    monkeypatch.setattr(settings, "llm_base_url", "")

    async with get_store().session(sessionmaker) as session:
        await svc.create(
            session, user, name="custom", base_url="https://custom.example", model="custom/model",
            api_key="sk-custom", enabled=True,
        )
        await svc.sync_active_to_settings(session, user.org_id)

    assert settings.llm_api_key == "sk-custom"
    assert settings.llm_model == "custom/model"
    assert settings.llm_base_url == "https://custom.example"


async def test_provider_patch_nonexistent_raises(provider_fixture):
    sessionmaker, user = provider_fixture
    from app.core.errors import AppError

    async with get_store().session(sessionmaker) as session:
        with pytest.raises(AppError):
            await ProviderService().patch(session, user, uuid.uuid4(), enabled=True)
