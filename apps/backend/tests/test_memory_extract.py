"""主动记忆提取分支测试（P1）：global 写卡 / skip / 消息尾部提取 / 失败静默 / 禁用开关。"""
from __future__ import annotations

import json
import uuid

from langchain_core.messages import AIMessage, HumanMessage

from app.services.memory_extract import _messages_tail, extract_and_store
from app.storage.file.store import get_store
from app.storage.repositories.memory import MemoryRepository


class FakeExtractModel:
    def __init__(self, content: str, *, raise_error: bool = False) -> None:
        self.content = content
        self.raise_error = raise_error

    async def ainvoke(self, messages):
        if self.raise_error:
            raise RuntimeError("LLM down")
        return AIMessage(content=self.content)


def _msgs(*pairs: tuple[str, str]) -> list:
    """构造 (role, content) 消息序列 → LangChain 消息列表。"""
    out = []
    for role, content in pairs:
        out.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))
    return out


async def _cards() -> list:
    return await get_store().table("memory_cards").list()


async def test_extract_global_preference_creates_card():
    """用户固定偏好 → global note 卡（source=extract，importance clamp，tags 落库）。"""
    uid = uuid.uuid4()
    plan = {
        "items": [
            {
                "scope": "global",
                "title": "代码风格偏好",
                "content": "用户希望代码尽量简洁、不要写多余注释",
                "importance": 0.9,
                "tags": ["偏好", "代码"],
                "topic_key": "code-style",
            }
        ]
    }
    result = await extract_and_store(
        messages=_msgs(("user", "我希望代码尽量简洁，不要写多余注释")),
        user_id=str(uid),
        model=FakeExtractModel(json.dumps(plan)),
    )
    assert result["status"] == "ok"
    assert result["extracted"] == 1
    cards = await _cards()
    assert len(cards) == 1
    card = cards[0]
    assert card.source == "extract"
    assert card.card_type == "note"
    assert card.title == "代码风格偏好"
    assert card.content == {"text": "用户希望代码尽量简洁、不要写多余注释"}
    assert card.importance == 0.9
    assert card.tags == ["偏好", "代码"]
    assert card.workspace_id is None  # 全局记忆


async def test_extract_skip_chat_creates_nothing():
    """闲聊/临时请求 → items 空 → 无卡片。"""
    uid = uuid.uuid4()
    result = await extract_and_store(
        messages=_msgs(("user", "帮我算一下 2+2"), ("assistant", "等于 4")),
        user_id=str(uid),
        model=FakeExtractModel(json.dumps({"items": []})),
    )
    assert result["status"] == "ok"
    assert result["extracted"] == 0
    assert await _cards() == []


async def test_extract_importance_clamped():
    """LLM 给的 importance 越界 → clamp 到 [0,1]。"""
    uid = uuid.uuid4()
    plan = {"items": [{"scope": "global", "title": "t", "content": "c", "importance": 5.0}]}
    await extract_and_store(
        messages=_msgs(("user", "我通常用 Vue3 开发")),
        user_id=str(uid),
        model=FakeExtractModel(json.dumps(plan)),
    )
    cards = await _cards()
    assert cards[0].importance == 1.0


async def test_extract_project_item_deferred_no_workspace():
    """project 项：无 workspace_root → 不落盘，pending 计数（P3 前仅日志）。"""
    uid = uuid.uuid4()
    plan = {
        "items": [
            {
                "scope": "project",
                "title": "架构决策",
                "content": "决定用 FastAPI",
                "importance": 0.8,
                "topic_key": "arch",
            }
        ]
    }
    result = await extract_and_store(
        messages=_msgs(("user", "我们决定用 FastAPI 做后端")),
        user_id=str(uid),
        model=FakeExtractModel(json.dumps(plan)),
    )
    assert result["status"] == "ok"
    assert result["project_pending"] == 1
    assert await _cards() == []  # project 不写卡片


async def test_extract_llm_error_silent():
    """LLM 故障 → status=error 返回 dict，不抛异常（记忆沉淀不击穿对话）。"""
    uid = uuid.uuid4()
    result = await extract_and_store(
        messages=_msgs(("user", "我喜欢喝咖啡")),
        user_id=str(uid),
        model=FakeExtractModel("{}", raise_error=True),
    )
    assert result["status"] == "error"
    assert "error" in result


async def test_extract_disabled_and_no_user():
    """禁用开关 / 无 user_id → 跳过，无副作用。"""
    from app.core.config import get_settings

    uid = uuid.uuid4()
    settings = get_settings()
    old = settings.memory_extract_enabled
    settings.memory_extract_enabled = False
    try:
        result = await extract_and_store(
            messages=_msgs(("user", "我喜欢喝咖啡")), user_id=str(uid), model=FakeExtractModel("{}")
        )
        assert result["status"] == "disabled"
    finally:
        settings.memory_extract_enabled = old
    result = await extract_and_store(
        messages=_msgs(("user", "我喜欢喝咖啡")), user_id=None, model=FakeExtractModel("{}")
    )
    assert result["status"] == "skipped"


async def test_messages_tail_only_last_user_and_after():
    """尾部提取：只取最后 user 及其后 assistant，历史轮不进入。"""
    msgs = _msgs(
        ("user", "旧问题1"),
        ("assistant", "旧回答1"),
        ("user", "旧问题2"),
        ("assistant", "旧回答2"),
        ("user", "本轮问题"),
        ("assistant", "本轮回答"),
    )
    tail = _messages_tail(msgs)
    assert tail == [("user", "本轮问题"), ("assistant", "本轮回答")]


async def test_messages_tail_dict_messages():
    """dict 形式消息（resume 重放/checkpoint 加载）同样可提取。"""
    tail = _messages_tail(
        [
            {"role": "user", "content": "历史"},
            {"role": "assistant", "content": "历史答"},
            {"role": "user", "content": "记住：我习惯用 Vue3+TS"},
        ]
    )
    assert tail == [("user", "记住：我习惯用 Vue3+TS")]


async def test_extract_writes_run_log():
    """提取结果落 run_log（type=memory_extract，落会话 trace 文件）。"""
    uid = uuid.uuid4()
    trace = uuid.uuid4().hex[:12]
    session_id = uuid.uuid4()
    plan = {"items": [{"scope": "global", "title": "t", "content": "c", "importance": 0.5}]}
    result = await extract_and_store(
        messages=_msgs(("user", "我的情况是经常出差")),
        user_id=str(uid),
        trace_id=trace,
        session_id=session_id,
        model=FakeExtractModel(json.dumps(plan)),
    )
    assert result["status"] == "ok"
    records = await MemoryRepository().store.jsonl_list(f"memory/default/trace/{session_id}.jsonl")
    extract_logs = [r for r in records if r.get("type") == "memory_extract"]
    assert len(extract_logs) == 1
    assert extract_logs[0]["trace_id"] == trace
    assert extract_logs[0]["output"]["extracted"] == 1


async def test_extract_global_card_persisted_to_disk():
    """review C1：提取写卡后显式 commit——卡片落 memory_cards.json（重启不丢）。"""
    import json as _json

    uid = uuid.uuid4()
    plan = {"items": [{"scope": "global", "title": "偏好", "content": "喜欢喝咖啡", "importance": 0.6}]}
    result = await extract_and_store(
        messages=_msgs(("user", "我喜欢喝咖啡")),
        user_id=str(uid),
        model=FakeExtractModel(json.dumps(plan)),
    )
    assert result["status"] == "ok" and result["extracted"] == 1
    # 磁盘文件已含卡片（非仅内存）
    json_path = get_store().root / "memory_cards.json"
    assert json_path.exists()
    data = _json.loads(json_path.read_text(encoding="utf-8"))
    items = data.get("items", {})
    assert len(items) == 1
    assert list(items.values())[0]["title"] == "偏好"
