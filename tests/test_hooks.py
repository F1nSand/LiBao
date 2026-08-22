"""M6 前开放项：hooks/webhook 端点测试（docs 03 §5.10）——注册/列表/接收（token 校验 + 幂等去重 + 事件入队）。"""
from __future__ import annotations

import uuid

import pytest

from app.core.errors import AppError
from app.services.events import drain_events
from app.services.webhook import WebhookService
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import Org, User
from app.tools.registry import ToolSpec, ToolType, register, unregister
from tests.conftest import requires_db, requires_redis

pytestmark = [requires_db, requires_redis]


@pytest.fixture
async def hook_fixture():
    from app.storage.redis import close_redis, init_redis

    init_redis()
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-hook-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"hook_{uid}", password_hash="hashed", name="H", role="admin", org_id=org.id)
        session.add(user)
        await session.commit()
    yield sessionmaker, user
    await close_redis()
    await engine.dispose()


def _event_tool() -> ToolSpec:
    return ToolSpec(
        id="tl_evt_demo", name="evt_demo", description="事件型演示工具",
        params_schema={"type": "object", "properties": {}, "required": []},
        tool_type=ToolType.EVENT, enabled=True,
    )


async def test_register_and_receive(hook_fixture):
    sessionmaker, user = hook_fixture
    register(_event_tool())
    svc = WebhookService()
    try:
        async with sessionmaker() as s:
            row = await svc.register(s, user, "tl_evt_demo", token="secret123")
            assert row.token_hash != "secret123"  # 只存 hash

            hooks = await svc.list(s, user)
            assert hooks[0]["tool_id"] == "tl_evt_demo"

            # 正确 token → 事件入队到 org 收件箱（安全点消费的原料）
            thread_key = f"org:{user.org_id}"
            drain_events(thread_key)
            processed = await svc.receive(s, "tl_evt_demo", "secret123", None, {"event": "new_email"})
            assert processed is True
            events = drain_events(thread_key)
            assert events and events[0]["type"] == "webhook"
            assert events[0]["tool_id"] == "tl_evt_demo"
            assert events[0]["payload"] == {"event": "new_email"}

            # 幂等：同 x-idempotency-key 去重（第二次返回 False）
            processed2 = await svc.receive(s, "tl_evt_demo", "secret123", "key-1", {"event": "dup"})
            processed3 = await svc.receive(s, "tl_evt_demo", "secret123", "key-1", {"event": "dup"})
            assert processed2 is True and processed3 is False

            # 注销后列表为空
            await svc.unregister(s, user, "tl_evt_demo")
            assert await svc.list(s, user) == []
    finally:
        unregister("tl_evt_demo")


async def test_wrong_token_and_non_event_tool(hook_fixture):
    sessionmaker, user = hook_fixture
    svc = WebhookService()
    register(_event_tool())
    register(
        ToolSpec(
            id="tl_not_evt", name="not_evt", description="非事件型", tool_type=ToolType.PERCEPTION, enabled=True
        )
    )
    try:
        async with sessionmaker() as s:
            await svc.register(s, user, "tl_evt_demo", token="secret123")
            # token 不匹配 → 401
            with pytest.raises(AppError) as exc:
                await svc.receive(s, "tl_evt_demo", "wrong", None, {})
            assert exc.value.code == 40103
            # 未注册工具 → 404
            with pytest.raises(AppError):
                await svc.receive(s, "tl_unknown", "x", None, {})
            # 非事件型工具不能注册
            with pytest.raises(AppError):
                await svc.register(s, user, "tl_not_evt", token="t")
    finally:
        unregister("tl_evt_demo")
        unregister("tl_not_evt")
