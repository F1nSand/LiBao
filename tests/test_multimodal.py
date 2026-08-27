"""多模态消息适配测试（2026-08-27）：能力判定 / 三分支构造 / 水合渲染 / 预算裁剪。"""
from __future__ import annotations

from app.core.multimodal import (
    ImagePayload,
    encode_image,
    fit_budget,
    human_message_with_images,
    is_image_mime,
    is_ref_block,
    make_ref_block,
    no_vision_note,
    render_message_content,
)
from app.core.vision import has_vision_pattern, supports_vision

# ---- B1 能力判定 ----


def test_vision_pattern_hits_and_misses():
    assert has_vision_pattern("gpt-4o")
    assert has_vision_pattern("qwen2.5-vl-72b-instruct")
    assert has_vision_pattern("glm-4v-flash")
    assert has_vision_pattern("claude-3.5-sonnet")
    assert not has_vision_pattern("deepseek-chat")
    assert not has_vision_pattern("deepseek-v4-flash")  # 推理≠视觉
    assert not has_vision_pattern("")
    assert not has_vision_pattern("qwen-max")  # 纯文本 qwen 文版不误判


def test_supports_vision_declared_overrides_pattern():
    # 显式声明优先（True/False 都压制 pattern）
    assert supports_vision("deepseek-chat", True) is True  # pattern 不命中但声明 vision
    assert supports_vision("gpt-4o", False) is False  # pattern 命中但硬压制
    # 未声明回落 pattern
    assert supports_vision("gpt-4o", None) is True
    assert supports_vision("deepseek-chat", None) is False


def test_provider_serialize_includes_capabilities():
    from app.storage.models.provider import ProviderConfig

    p = ProviderConfig(org_id=__import__("uuid").uuid4(), name="x", capabilities=["vision"])
    from app.services.provider import serialize_provider

    d = serialize_provider(p)
    assert d["capabilities"] == ["vision"]
    p2 = ProviderConfig(org_id=__import__("uuid").uuid4(), name="y")
    assert serialize_provider(p2)["capabilities"] == []


def test_provider_old_json_without_capabilities_loads():
    """旧 providers.json 行无 capabilities 字段 → rows.from_dict 补默认值 []（向后兼容）。"""
    from app.storage.models.provider import ProviderConfig

    row = ProviderConfig.from_dict({"org_id": "00000000-0000-0000-0000-000000000001", "name": "old"})
    assert row.capabilities == []


async def test_sync_active_pushes_vision_declared(monkeypatch):
    """activate/sync 后 capabilities → settings.llm_vision_declared（vision→True/空→None/其他→False）。"""
    import uuid as _uuid

    from app.core.config import get_settings
    from app.services.provider import ProviderService
    from app.storage.file.store import get_store
    from app.storage.models import User
    from app.storage.repositories.provider import ProviderRepository

    uid = _uuid.uuid4().hex[:8]
    store = get_store()
    async with store.session() as session:
        await session.flush()
        user = User(username=f"vis_{uid}", password_hash="h", name="V", role="admin", org_id=_uuid.UUID(int=0))
        session.add(user)
        await session.commit()
        svc = ProviderService()

        monkeypatch.setattr(get_settings(), "llm_vision_declared", None)
        await svc.create(session, user, name="a", model="m", enabled=True, capabilities=["vision"])
        await svc.sync_active_to_settings(session, user.org_id)
        assert get_settings().llm_vision_declared is True

        await svc.create(session, user, name="b", model="m2", enabled=True)  # activate b → a 停
        rows = await ProviderRepository(session).list_for_org(user.org_id)
        target = next(r for r in rows if r.name == "b")
        await svc.activate(session, user, target.id)
        assert get_settings().llm_vision_declared is None  # 空 caps → 未声明

        cap_row = next(r for r in rows if r.name == "a")
        await svc.patch(session, user, cap_row.id, capabilities=["text-only"])  # 非 vision 声明
        await svc.activate(session, user, cap_row.id)
        assert get_settings().llm_vision_declared is False  # 硬压制


def test_is_image_mime():
    assert is_image_mime("image/png")
    assert is_image_mime("IMAGE/JPEG")  # 大小写不敏感
    assert not is_image_mime("application/pdf")
    assert not is_image_mime(None)


# ---- B2 三分支消息构造 ----


def test_human_message_no_refs_byte_identical():
    """无图 → str content 与现状逐字节相同（零回归锚点）。"""
    m = human_message_with_images("你好", [], True)
    assert m.content == "你好"
    m2 = human_message_with_images("你好", [], False)
    assert m2.content == "你好"


def test_human_message_vision_with_refs_list_blocks():
    refs = [make_ref_block("att-1", "image/png"), make_ref_block("att-2", "image/jpeg")]
    m = human_message_with_images("看这两张图", refs, vision=True)
    assert isinstance(m.content, list)
    assert [b for b in m.content if is_ref_block(b)] == refs  # ref 在前
    text_blocks = [b for b in m.content if b.get("type") == "text"]
    assert len(text_blocks) == 1 and text_blocks[0]["text"] == "看这两张图"  # 无 drop 注记时原文干净


def test_human_message_non_vision_inline_note():
    """非视觉模型有图 → str 注记前缀 + 原文；ref 全丢弃；含被剔数表述。"""
    refs = [make_ref_block("att-1", "image/png")]
    m = human_message_with_images("看看", refs, vision=False, model="deepseek-chat", n_dropped=1)
    assert isinstance(m.content, str)
    assert "deepseek-chat" in m.content and "不支持读取图片" in m.content and "1 张" in m.content
    assert "超过单轮大小预算" in m.content  # n_dropped 声明
    assert m.content.endswith("\n\n看看")
    # 无 drop 时不含预算句
    m2 = human_message_with_images("看看", refs, vision=False, model="deepseek-chat")
    assert "预算" not in m2.content


# ---- render_view 水合 ----


def _payload(att_id: str, mime: str = "image/png") -> ImagePayload:
    return ImagePayload(att_id=att_id, mime=mime, data_b64=encode_image(b"fakebytes"))


def test_render_current_round_ref_hydrates_image_block():
    p = _payload("att-1")
    content = [make_ref_block("att-1", "image/png"), {"type": "text", "text": "hi"}]
    out = render_message_content(content, index={"att-1": p}, current_ids={"att-1"}, vision=True)
    assert out[0] == {"type": "image", "source_type": "base64", "data": p.data_b64, "mime_type": "image/png"}
    assert out[1] == {"type": "text", "text": "hi"}


def test_render_historical_ref_degrades_to_text_marker():
    p = _payload("att-1")
    content = [make_ref_block("att-hist", "image/png"), {"type": "text", "text": "hi"}]
    out = render_message_content(content, index={"att-1": p}, current_ids={"att-1"}, vision=True)
    assert "已省略" in out[0]["text"]  # 历史 ref → 文本标记，绝不水合旧图
    assert all(not is_ref_block(b) for b in out)  # ref 全部被消化


def test_render_non_vision_or_missing_payload_degrades():
    content = [make_ref_block("att-x", "image/png")]
    # vision 但 payload 缺失
    out1 = render_message_content(content, index={}, current_ids={"att-x"}, vision=True)
    assert "已省略" in out1[0]["text"]
    # payload 在但非 vision
    p = _payload("att-x")
    out2 = render_message_content(content, index={"att-x": p}, current_ids={"att-x"}, vision=False)
    assert "已省略" in out2[0]["text"]
    # image_ctx None 路径等价于原始引用不变（str 直通）
    assert render_message_content("plain", index={"att-x": p}, current_ids={"att-x"}, vision=True) == "plain"


def test_render_no_ref_list_passthrough():
    blocks = [{"type": "text", "text": "a"}]
    assert render_message_content(blocks, index={}, current_ids=set(), vision=True) is blocks  # 幂等同对象


# ---- 预算裁剪 ----


def test_fit_budget_within_limit_keeps_all():
    small = [_payload(f"a{i}") for i in range(3)]
    kept, dropped = fit_budget(small, budget_mb=10)
    assert (kept, dropped) == (small, 0)


def test_fit_budget_drops_overflow_tail_and_counts():
    big = ImagePayload(att_id="big", mime="image/png", data_b64=encode_image(b"x" * (6 * 1024 * 1024)))
    small = _payload("s")
    kept, dropped = fit_budget([small, big], budget_mb=5)  # b64 还原后 big≈6MB > 剩余预算
    assert dropped == 1 and len(kept) == 1
    # 单张即超限：剔该张继续后面的
    huge = ImagePayload(att_id="huge", mime="image/png", data_b64=encode_image(b"x" * (8 * 1024 * 1024)))
    kept2, dropped2 = fit_budget([huge, small], budget_mb=5)
    assert dropped2 == 1 and [p.att_id for p in kept2] == ["s"]
    # note 含被剔数
    assert "1 张图片因超过单轮大小预算" in no_vision_note("m", 2, 1)
