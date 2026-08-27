"""M6 前：Provider 配置测试（DB-backed）——CRUD + api_key 只写不读（has_key）+ 启动同步。"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.provider import ProviderService, serialize_provider
from app.storage.file.store import get_store
from app.storage.models import User


@pytest.fixture
async def provider_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"pv_{uid}", password_hash="hashed", name="P", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.commit()
    yield user


async def test_provider_crud_and_api_key_write_only(provider_fixture):
    user = provider_fixture
    svc = ProviderService()
    async with get_store().session() as session:
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
    user = provider_fixture
    svc = ProviderService()
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "default/model")
    monkeypatch.setattr(settings, "llm_base_url", "")

    async with get_store().session() as session:
        await svc.create(
            session, user, name="custom", base_url="https://custom.example", model="custom/model",
            api_key="sk-custom", enabled=True,
        )
        await svc.sync_active_to_settings(session, uuid.UUID(int=0))

    assert settings.llm_api_key == "sk-custom"
    assert settings.llm_model == "custom/model"
    assert settings.llm_base_url == "https://custom.example"


async def test_provider_patch_nonexistent_raises(provider_fixture):
    user = provider_fixture
    from app.core.errors import AppError

    async with get_store().session() as session:
        with pytest.raises(AppError):
            await ProviderService().patch(session, user, uuid.uuid4(), enabled=True)


async def test_provider_activate_unique_and_hot_sync(provider_fixture, monkeypatch):
    """activate：唯一激活（其余停用）+ 热同步 Settings（base_url 归一化为 OpenAI base）。"""
    user = provider_fixture
    svc = ProviderService()
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "default")
    monkeypatch.setattr(settings, "llm_base_url", "")

    async with get_store().session() as session:
        p1 = await svc.create(
            session, user, name="p1", base_url="https://a.com", model="m1", api_key="k1", enabled=True
        )
        p2 = await svc.create(
            session, user, name="p2", base_url="https://b.com/v1/chat/completions",
            model="m2", api_key="k2", enabled=True, is_full_url=True,
        )
        activated = await svc.activate(session, user, p2.id)
        assert activated.id == p2.id
        listed = await svc.list(session, user)
        enabled_by_id = {p["id"]: p["enabled"] for p in listed}
        assert enabled_by_id[str(p1.id)] is False  # 其余停用
        assert enabled_by_id[str(p2.id)] is True
        assert settings.llm_model == "m2"  # 热同步
        assert settings.llm_api_key == "k2"
        assert settings.llm_base_url == "https://b.com/v1"  # 完整 URL 剥 /chat/completions


async def test_provider_patch_enable_activates_uniquely_and_hot_syncs(provider_fixture, monkeypatch):
    """前端开关 PATCH enabled=true：等价 activate，切回 DeepSeek 后立即使用其推理模型。"""
    user = provider_fixture
    svc = ProviderService()
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "glm-key")
    monkeypatch.setattr(settings, "llm_model", "glm-5.3-flash")
    monkeypatch.setattr(settings, "llm_base_url", "https://open.bigmodel.cn/api/paas/v4")

    async with get_store().session() as session:
        glm = await svc.create(
            session,
            user,
            name="glm",
            base_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            is_full_url=True,
            model="glm-5.3-flash",
            api_key="glm-key",
            enabled=True,
        )
        deepseek = await svc.create(
            session,
            user,
            name="deepseek",
            base_url="https://old.deepseek.example/v1",
            is_full_url=False,
            model="deepseek-chat",
            api_key="old-deepseek-key",
            enabled=False,
        )

        patched = await svc.patch(
            session,
            user,
            deepseek.id,
            enabled=True,
            base_url="https://api.deepseek.com/v1/chat/completions",
            is_full_url=True,
            model="deepseek-v4-flash",
            api_key="deepseek-key",
        )
        listed = await svc.list(session, user)

    enabled_by_id = {p["id"]: p["enabled"] for p in listed}
    assert patched.id == deepseek.id
    assert enabled_by_id[str(glm.id)] is False
    assert enabled_by_id[str(deepseek.id)] is True
    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.llm_base_url == "https://api.deepseek.com/v1"
    assert settings.llm_api_key == "deepseek-key"

    from app.orchestration.stream_core import resolve_effective_model

    assert resolve_effective_model(SimpleNamespace(model="")) == "deepseek-v4-flash"


async def test_provider_serialize_new_fields(provider_fixture):
    user = provider_fixture
    svc = ProviderService()
    async with get_store().session() as session:
        p = await svc.create(
            session, user, name="我的 DeepSeek", website="https://platform.deepseek.com",
            base_url="https://api.deepseek.com", is_full_url=False, model="deepseek-chat", api_key="sk-x",
        )
        d = serialize_provider(p)
        assert d["name"] == "我的 DeepSeek"
        assert d["website"] == "https://platform.deepseek.com"
        assert d["is_full_url"] is False
        assert d["model"] == "deepseek-chat"
        assert d["has_key"] is True
        assert "api_key" not in d  # 明文永不回传


async def test_provider_patch_clears_null(provider_fixture):
    """PATCH 显式传 None = 清空（修复现状 patch 无法清空 base_url/api_key 的 bug）。"""
    user = provider_fixture
    svc = ProviderService()
    async with get_store().session() as session:
        p = await svc.create(session, user, name="p", base_url="https://a.com", model="m", api_key="k")
        patched = await svc.patch(session, user, p.id, base_url=None, api_key=None)
        assert patched.base_url is None
        assert patched.api_key is None
        assert patched.model == "m"  # 未传不动


async def test_provider_get_active_returns_enabled(provider_fixture):
    user = provider_fixture
    svc = ProviderService()
    async with get_store().session() as session:
        await svc.create(session, user, name="p1", model="m1", enabled=False)
        p2 = await svc.create(session, user, name="p2", model="m2", enabled=True)
        active = await svc.get_active(session, user)
        assert active is not None and active.id == p2.id
