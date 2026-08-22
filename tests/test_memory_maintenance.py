"""T4 maintenance 测试（DB-backed，FakeChatModel 注入）：LLM 整理 create/update/delete、
围栏 JSON 提取、非法 JSON/LLM 异常 → 60001、importance clamp。
"""
from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.core.errors import AppError
from app.services.memory import MemoryService, _extract_json, run_maintenance
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, User
from app.storage.models.memory import LongTermMemoryVersion
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.message import MessageRepository
from tests.conftest import requires_db

pytestmark = requires_db


class FakeMaintainModel:
    def __init__(self, content: str, *, raise_error: bool = False) -> None:
        self.content = content
        self.raise_error = raise_error

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        if self.raise_error:
            raise RuntimeError("LLM down")
        return AIMessage(content=self.content)


@pytest.fixture
async def maint_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"maint_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.commit()
    yield user


def test_extract_json_plain_and_fenced():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('前缀 {"a": 1} 后缀') == {"a": 1}
    with pytest.raises(ValueError):
        _extract_json("不是 JSON")


async def test_maintenance_applies_plan(maint_fixture):
    user = maint_fixture
    async with get_store().session() as session:
        svc = MemoryService()
        keep = await svc.create_card(session, user.id, "note", "保留", {"text": "keep"})
        upd = await svc.create_card(session, user.id, "note", "更新", {"text": "old"}, importance=0.3)
        dele = await svc.create_card(session, user.id, "note", "删除", {"text": "bye"})
        # maintenance 改读 messages：造一条 user 消息作为整理原料
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="maint-agent", model="fake", system_prompt="x", tools=[], max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.flush()
        conv = await ConversationRepository(session).create(
            user_id=user.id, agent_id=agent.id, title="maint-conv"
        )
        await MessageRepository(session).create(conversation_id=conv.id, role="user", content="用户说喜欢喝咖啡")

        plan = {
            "keep": [str(keep.id)],
            "update": [{"id": str(upd.id), "content": {"text": "new"}, "importance": 0.9}],
            "create": [{"content": {"text": "新卡片"}, "importance": 0.7, "card_type": "note"}],
            "delete": [str(dele.id)],
        }
        result = await run_maintenance(session, user.id, model=FakeMaintainModel(json.dumps(plan)))
        assert result["cards_created"] == 1
        assert result["cards_updated"] == 1
        # keep 不变
        assert (await svc.get_card(session, user.id, keep.id)).content == {"text": "keep"}
        # update → 新版本
        upd2 = await svc.get_card(session, user.id, upd.id)
        assert upd2.content == {"text": "new"}
        assert upd2.importance == 0.9
        assert upd2.current_version == 2
        versions = await svc.list_versions(session, user.id, upd.id)
        assert len(versions) == 2
        # create → source=maintenance
        cards = await svc.list_cards(session, user.id)
        created = [c for c in cards if c.source == "maintenance"]
        assert len(created) == 1 and created[0].content == {"text": "新卡片"}
        # delete → 软删
        with pytest.raises(AppError) as exc:
            await svc.get_card(session, user.id, dele.id)
        assert exc.value.code == 40409


async def test_maintenance_fenced_json(maint_fixture):
    user = maint_fixture
    async with get_store().session() as session:
        plan = {"keep": [], "update": [], "create": [], "delete": []}
        result = await run_maintenance(
            session, user.id, model=FakeMaintainModel(f"```json\n{json.dumps(plan)}\n```")
        )
        assert result["cards_created"] == 0


async def test_maintenance_invalid_json_60001(maint_fixture):
    user = maint_fixture
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await run_maintenance(session, user.id, model=FakeMaintainModel("这不是 JSON"))
        assert exc.value.code == 60001
        assert exc.value.retryable is True


async def test_maintenance_llm_error_60001(maint_fixture):
    user = maint_fixture
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await run_maintenance(session, user.id, model=FakeMaintainModel("{}", raise_error=True))
        assert exc.value.code == 60001


async def test_maintenance_invalid_update_id_60001(maint_fixture):
    """C2/S4：LLM 输出合法 JSON 但 update id 非法 UUID → 60001 retryable（非裸 500）。"""
    user = maint_fixture
    async with get_store().session() as session:
        plan = {"update": [{"id": "not-a-uuid", "content": {"text": "x"}}], "create": [], "delete": []}
        with pytest.raises(AppError) as exc:
            await run_maintenance(session, user.id, model=FakeMaintainModel(json.dumps(plan)))
        assert exc.value.code == 60001
        assert exc.value.retryable is True


async def test_maintenance_version_append_after_external_write(maint_fixture):
    """文件化后无 UNIQUE 约束：外部写入 v2 后 maintenance 按 current_version 追加 v3（append-only）。"""
    user = maint_fixture
    async with get_store().session() as session:
        svc = MemoryService()
        card = await svc.create_card(session, user.id, "note", "并发", {"text": "v1"})
        # 模拟外部已写入 version=2（JSONL append）
        await get_store().jsonl_append(
            f"memory/default/cards/{card.id}.versions.jsonl",
            LongTermMemoryVersion(memory_id=card.id, version=2, content={"text": "外部 v2"}, importance=0.5).to_dict(),
        )
        await session.commit()
    async with get_store().session() as session:
        plan = {"update": [{"id": str(card.id), "content": {"text": "本会话 v2"}, "importance": 0.8}]}
        await run_maintenance(session, user.id, model=FakeMaintainModel(json.dumps(plan)))
        # 文件化无 UNIQUE 约束：外部 v2 与本会话 v2 并存（append-only 追加，不抛错）
        versions = await MemoryService().list_versions(session, user.id, card.id)
        assert len(versions) == 3  # v1 + 外部 v2 + 本会话追加


async def test_maintenance_importance_clamped(maint_fixture):
    user = maint_fixture
    async with get_store().session() as session:
        plan = {
            "keep": [],
            "update": [],
            "create": [{"content": {"text": "x"}, "importance": 5.0, "card_type": "note"}],
            "delete": [],
        }
        await run_maintenance(session, user.id, model=FakeMaintainModel(json.dumps(plan)))
        cards = await MemoryService().list_cards(session, user.id)
        assert cards[0].importance == 1.0  # clamp 到 [0,1]


async def test_maintenance_reads_recent_messages(maint_fixture):
    """run_maintenance 改读 messages（memory_trace 已删）：LLM 收到最近对话含 user+assistant 消息。"""
    user = maint_fixture
    async with get_store().session() as session:
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="maint-agent", model="fake", system_prompt="x", tools=[], max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.flush()
        conv = await ConversationRepository(session).create(
            user_id=user.id, agent_id=agent.id, title="maint-conv"
        )
        await MessageRepository(session).create(conversation_id=conv.id, role="user", content="用户说喜欢喝咖啡")
        await MessageRepository(session).create(conversation_id=conv.id, role="assistant", content="已记录偏好")
        await session.commit()
    captured: dict[str, str] = {}

    class CaptureModel(FakeMaintainModel):
        async def ainvoke(self, messages):
            captured["prompt"] = messages[0].content
            return AIMessage(content=json.dumps({"keep": [], "update": [], "create": [], "delete": []}))

    async with get_store().session() as session:
        await run_maintenance(session, user.id, model=CaptureModel("{}"))  # content 占位，ainvoke 被覆写
    assert "用户说喜欢喝咖啡" in captured["prompt"]
    assert "已记录偏好" in captured["prompt"]
