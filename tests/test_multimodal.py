"""多模态消息适配测试（2026-08-27）：能力判定 / 三分支构造 / 水合渲染 / 预算裁剪。"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.orchestration.multimodal_input as multimodal_input
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.model_capabilities import ModelCapabilityKey, VisionCapability, VisionDecision
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
from app.orchestration.context_builder import build_context
from app.orchestration.multimodal_input import PreparedImageInput, image_config, prepare_image_input
from app.orchestration.nodes.agent_execute import _image_ctx
from app.orchestration.stream_core import build_initial_state

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


def test_human_message_vision_with_image_only_omits_empty_text_block():
    """纯图片请求不能携带空 text block（智谱等兼容端点会以 1210 拒绝）。"""
    refs = [make_ref_block("att-1", "image/png")]
    message = human_message_with_images("", refs, vision=True)

    assert message.content == refs


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


# ---- Task 6：统一、带 owner 的图片准备 ----


async def test_prepare_image_input_owner_order_and_mime(monkeypatch):
    user_id = uuid.uuid4()
    first_id, pdf_id, second_id, foreign_id = (uuid.uuid4() for _ in range(4))
    rows = {
        first_id: SimpleNamespace(id=first_id, user_id=user_id, content_type="image/png"),
        pdf_id: SimpleNamespace(id=pdf_id, user_id=user_id, content_type="application/pdf"),
        second_id: SimpleNamespace(id=second_id, user_id=user_id, content_type="image/jpeg"),
        foreign_id: SimpleNamespace(id=foreign_id, user_id=uuid.uuid4(), content_type="image/png"),
    }
    seen_owner_ids: list[tuple[uuid.UUID, uuid.UUID]] = []
    reads: list[uuid.UUID] = []

    class FakeAttachmentRepository:
        def __init__(self, db):
            pass

        async def get(self, owner_id, attachment_id):
            seen_owner_ids.append((owner_id, attachment_id))
            row = rows.get(attachment_id)
            return row if row is not None and row.user_id == owner_id else None

    async def read_file(self, row):
        reads.append(row.id)
        return b"bytes-" + str(row.id).encode()

    monkeypatch.setattr("app.orchestration.multimodal_input.AttachmentRepository", FakeAttachmentRepository)
    monkeypatch.setattr("app.orchestration.multimodal_input.AttachmentService.read_file", read_file)
    monkeypatch.setattr(get_settings(), "llm_vision_declared", True)

    result = await prepare_image_input(
        object(),
        user_id=user_id,
        attachment_ids=[str(second_id), str(pdf_id), str(first_id), str(foreign_id)],
        effective_model="deepseek-chat",
    )

    assert [ref["attachment_id"] for ref in result.image_refs] == [str(second_id), str(first_id)]
    assert list(result.image_payload) == [str(second_id), str(first_id)]
    assert result.candidate_count == 2 and result.omitted_count == 0 and result.vision is True
    assert reads == [second_id, first_id]
    assert all("data_b64" not in ref and "bytes" not in ref for ref in result.image_refs)
    assert all(owner == user_id for owner, _ in seen_owner_ids)


@pytest.mark.asyncio
async def test_prepare_image_input_plain_turn_skips_capability_discovery(monkeypatch):
    class Resolver:
        async def resolve_vision(self, key, api_key=None):
            raise AssertionError("plain turns must not discover image capability")

    monkeypatch.setattr(multimodal_input, "get_model_capability_resolver", lambda: Resolver())

    class EmptyRepository:
        def __init__(self, db):
            pass

        async def get(self, owner_id, attachment_id):
            return None

    monkeypatch.setattr(multimodal_input, "AttachmentRepository", EmptyRepository)
    result = await prepare_image_input(
        object(), user_id=uuid.uuid4(), attachment_ids=[], effective_model="glm-5.3-flash"
    )
    assert result.candidate_count == 0 and result.capability is VisionCapability.UNKNOWN


async def test_prepare_image_input_non_vision_never_reads_files(monkeypatch):
    user_id = uuid.uuid4()
    image_id = uuid.uuid4()
    row = SimpleNamespace(id=image_id, user_id=user_id, content_type="image/png")
    reads = 0

    class FakeAttachmentRepository:
        def __init__(self, db):
            pass

        async def get(self, owner_id, attachment_id):
            return row if owner_id == user_id and attachment_id == image_id else None

    async def read_file(_row):
        nonlocal reads
        reads += 1
        raise AssertionError("non-vision preparation must not read image files")

    monkeypatch.setattr("app.orchestration.multimodal_input.AttachmentRepository", FakeAttachmentRepository)
    monkeypatch.setattr("app.orchestration.multimodal_input.AttachmentService.read_file", read_file)

    class Resolver:
        async def resolve_vision(self, key, api_key=None):
            return VisionDecision(VisionCapability.UNSUPPORTED, "metadata", key)

    monkeypatch.setattr(multimodal_input, "get_model_capability_resolver", lambda: Resolver())

    result = await prepare_image_input(
        object(), user_id=user_id, attachment_ids=[str(image_id)], effective_model="gpt-4o"
    )

    assert result.vision is False
    assert result.candidate_count == 1 and result.omitted_count == 0
    assert result.image_refs == () and result.image_payload == {}
    assert reads == 0


def test_image_config_force_context_preserves_nonempty_prepared_payload():
    payload = _payload("att-1")
    prepared = PreparedImageInput(
        image_refs=(make_ref_block("att-1", "image/png"),),
        image_payload={"att-1": payload},
        current_image_ids=frozenset({"att-1"}),
        candidate_count=1,
        omitted_count=0,
        vision=True,
    )

    config = image_config(prepared, force_context=True)

    assert config["image_payload"] == {"att-1": payload}
    assert config["current_image_ids"] == {"att-1"}
    assert config["vision"] is True


def test_image_config_force_context_emits_empty_keys_for_empty_prepared():
    prepared = PreparedImageInput(
        image_refs=(),
        image_payload={},
        current_image_ids=frozenset(),
        candidate_count=0,
        omitted_count=0,
        vision=True,
    )

    config = image_config(prepared, force_context=True)

    assert config == {"image_payload": {}, "current_image_ids": set(), "vision": False}
    assert image_config(None, force_context=False) == {}


def test_human_message_non_vision_does_not_duplicate_omission_count():
    message = human_message_with_images(
        "原始问题",
        [],
        vision=False,
        model="deepseek-chat",
        n_images=2,
        n_dropped=0,
    )

    assert message.content.count("2 张图片") == 1
    assert "另有" not in message.content
    assert "预算" not in message.content
    assert "读取失败" not in message.content
    assert message.content.endswith("\n\n原始问题")


async def test_prepare_image_input_counts_read_failures_and_budget_drops(monkeypatch):
    user_id = uuid.uuid4()
    kept_id, unreadable_id, oversized_id = (uuid.uuid4() for _ in range(3))
    rows = {
        att_id: SimpleNamespace(id=att_id, user_id=user_id, content_type="image/png")
        for att_id in (kept_id, unreadable_id, oversized_id)
    }

    class FakeAttachmentRepository:
        def __init__(self, db):
            pass

        async def get(self, owner_id, attachment_id):
            return rows.get(attachment_id) if owner_id == user_id else None

    async def read_file(_service, row):
        if row.id == unreadable_id:
            raise OSError("missing file")
        return b"x" * (100 if row.id == kept_id else 2 * 1024 * 1024)

    monkeypatch.setattr("app.orchestration.multimodal_input.AttachmentRepository", FakeAttachmentRepository)
    monkeypatch.setattr("app.orchestration.multimodal_input.AttachmentService.read_file", read_file)
    monkeypatch.setattr(get_settings(), "llm_vision_declared", True)
    monkeypatch.setattr(get_settings(), "image_total_budget_mb", 1)

    result = await prepare_image_input(
        object(),
        user_id=user_id,
        attachment_ids=[str(kept_id), str(unreadable_id), str(oversized_id)],
        effective_model="gpt-4o",
    )

    assert result.candidate_count == 3 and result.omitted_count == 2
    assert [ref["attachment_id"] for ref in result.image_refs] == [str(kept_id)]
    assert set(result.image_payload) == {str(kept_id)}


def test_empty_image_context_converts_refs_to_fallback():
    ctx = _image_ctx(
        {"configurable": {"image_payload": {}, "current_image_ids": set(), "vision": False}}
    )
    assert ctx is not None
    state = {
        "agent_config": {"system_prompt": "system"},
        "messages": [
            __import__("langchain_core.messages", fromlist=["HumanMessage"]).HumanMessage(
                content=[make_ref_block("att-historical", "image/png"), {"type": "text", "text": "看图"}]
            )
        ],
    }
    rendered = build_context(state, image_ctx=ctx)
    human = next(m for m in rendered if m.type == "human")
    assert all(not is_ref_block(block) for block in human.content)
    assert "图片已省略" in human.content[0]["text"]


def test_initial_state_reports_omission_when_no_image_survives(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(get_settings(), "llm_vision_declared", True)
    agent = SimpleNamespace(
        tools=[],
        system_prompt="system",
        model="gpt-4o",
        max_steps=5,
        name="vision",
        org_id=uuid.uuid4(),
    )
    state = build_initial_state(
        agent,
        "描述",
        image_refs=[],
        image_candidate_count=2,
        image_omitted_count=2,
    )
    assert "2" in state["messages"][0].content
    assert "未能送达" in state["messages"][0].content


@pytest.mark.asyncio
async def test_glm_53_flash_unknown_capability_reads_and_prepares_image(monkeypatch):
    user_id = uuid.uuid4()
    image_id = uuid.uuid4()
    row = SimpleNamespace(id=image_id, content_type="image/png")
    reads: list[uuid.UUID] = []

    class Repo:
        def __init__(self, db):
            self.db = db

        async def get(self, owner_id, attachment_id):
            assert owner_id == user_id
            return row if attachment_id == image_id else None

    class Resolver:
        async def resolve_vision(self, key, api_key=None):
            assert key.model == "glm-5.3-flash"
            return VisionDecision(VisionCapability.UNKNOWN, "unknown", key)

    async def read_file(att):
        reads.append(att.id)
        return b"png bytes"

    monkeypatch.setattr(multimodal_input, "AttachmentRepository", Repo)
    monkeypatch.setattr(multimodal_input, "AttachmentService", lambda: SimpleNamespace(read_file=read_file))
    monkeypatch.setattr(multimodal_input, "get_model_capability_resolver", lambda: Resolver())

    result = await prepare_image_input(
        object(),
        user_id=user_id,
        attachment_ids=[str(image_id)],
        effective_model="glm-5.3-flash",
        effective_base_url="https://custom.example.test/v1",
    )

    assert result.capability is VisionCapability.UNKNOWN
    assert reads == [image_id]
    assert list(result.image_payload) == [str(image_id)]


@pytest.mark.asyncio
async def test_authoritative_unsupported_never_reads_image(monkeypatch):
    user_id = uuid.uuid4()
    image_id = uuid.uuid4()
    row = SimpleNamespace(id=image_id, content_type="image/png")
    reads: list[uuid.UUID] = []

    class Repo:
        def __init__(self, db):
            self.db = db

        async def get(self, owner_id, attachment_id):
            return row if owner_id == user_id and attachment_id == image_id else None

    class Resolver:
        async def resolve_vision(self, key, api_key=None):
            return VisionDecision(VisionCapability.UNSUPPORTED, "metadata", key)

    async def read_file(att):
        reads.append(att.id)
        return b"should not be read"

    monkeypatch.setattr(multimodal_input, "AttachmentRepository", Repo)
    monkeypatch.setattr(multimodal_input, "AttachmentService", lambda: SimpleNamespace(read_file=read_file))
    monkeypatch.setattr(multimodal_input, "get_model_capability_resolver", lambda: Resolver())

    result = await prepare_image_input(
        object(),
        user_id=user_id,
        attachment_ids=[str(image_id)],
        effective_model="custom-text",
        effective_base_url="https://custom.example.test/v1",
    )

    assert result.capability is VisionCapability.UNSUPPORTED
    assert result.candidate_count == 1
    assert result.image_refs == () and result.image_payload == {}
    assert reads == []


@pytest.mark.asyncio
async def test_unknown_image_success_records_supported(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage

    from app.orchestration.nodes import agent_execute as agent_execute_module

    key = ModelCapabilityKey("https://custom.example.test/v1", "glm-5.3-flash")
    payload = ImagePayload(att_id="att-1", mime="image/png", data_b64="cG5n")
    calls: list[list] = []

    class Resolver:
        def __init__(self):
            self.successes = []

        def record_success(self, seen_key):
            self.successes.append(seen_key)

        def record_unsupported(self, seen_key):
            raise AssertionError("unexpected negative result")

    resolver = Resolver()

    class Model:
        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            calls.append(messages)
            return AIMessage(content="ok", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})

    monkeypatch.setattr(agent_execute_module, "get_model_capability_resolver", lambda: resolver)
    state = {
        "agent_config": {"model": "glm-5.3-flash", "system_prompt": "", "tools": [], "max_steps": 5},
        "messages": [HumanMessage(content=[make_ref_block("att-1", "image/png")])],
        "flags": {},
        "totals": {},
        "run_logs": [],
    }
    config = {
        "configurable": {
            "model": Model(),
            "image_payload": {"att-1": payload},
            "current_image_ids": {"att-1"},
            "vision": True,
            "image_capability_state": VisionCapability.UNKNOWN.value,
            "image_capability_key": key,
        }
    }

    await agent_execute_module.agent_execute_node(state, config)

    assert calls and any(block.get("type") == "image" for block in calls[0][1].content)
    assert resolver.successes == [key]


@pytest.mark.asyncio
async def test_explicit_image_rejection_is_not_retried_and_records_negative(monkeypatch):
    from langchain_core.messages import HumanMessage

    from app.orchestration.nodes import agent_execute as agent_execute_module

    key = ModelCapabilityKey("https://custom.example.test/v1", "glm-5.3-flash")
    resolver_calls: list[tuple[str, ModelCapabilityKey]] = []

    class Resolver:
        def record_success(self, seen_key):
            resolver_calls.append(("success", seen_key))

        def record_unsupported(self, seen_key):
            resolver_calls.append(("unsupported", seen_key))

    class Model:
        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            exc = RuntimeError("vision_not_supported: image input is unsupported")
            exc.status_code = 400
            raise exc

    monkeypatch.setattr(agent_execute_module, "get_model_capability_resolver", lambda: Resolver())
    state = {
        "agent_config": {"model": "glm-5.3-flash", "system_prompt": "", "tools": [], "max_steps": 5},
        "messages": [HumanMessage(content=[make_ref_block("att-1", "image/png")])],
        "flags": {},
        "totals": {},
        "run_logs": [],
    }
    config = {
        "configurable": {
            "model": Model(),
            "image_payload": {"att-1": ImagePayload(att_id="att-1", mime="image/png", data_b64="cG5n")},
            "current_image_ids": {"att-1"},
            "vision": True,
            "image_capability_state": VisionCapability.UNKNOWN.value,
            "image_capability_key": key,
        }
    }

    with pytest.raises(AppError) as exc:
        await agent_execute_module.agent_execute_node(state, config)

    assert exc.value.code == 60005
    assert resolver_calls == [("unsupported", key)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        type("Transient400", (RuntimeError,), {"status_code": 400})("bad request"),
        type("Unauthorized", (RuntimeError,), {"status_code": 401})("unauthorized"),
        type("RateLimited", (RuntimeError,), {"status_code": 429})("rate limited"),
        type("ServerError", (RuntimeError,), {"status_code": 500})("server error"),
        TimeoutError("request timed out"),
    ],
)
async def test_transient_image_failure_does_not_poison_capability_cache(monkeypatch, error):
    from langchain_core.messages import HumanMessage

    from app.orchestration.nodes import agent_execute as agent_execute_module

    key = ModelCapabilityKey("https://custom.example.test/v1", "glm-5.3-flash")
    resolver_calls: list[tuple[str, ModelCapabilityKey]] = []

    class Resolver:
        def record_success(self, seen_key):
            resolver_calls.append(("success", seen_key))

        def record_unsupported(self, seen_key):
            resolver_calls.append(("unsupported", seen_key))

    class Model:
        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            raise error

    monkeypatch.setattr(agent_execute_module, "get_model_capability_resolver", lambda: Resolver())
    state = {
        "agent_config": {"model": "glm-5.3-flash", "system_prompt": "", "tools": [], "max_steps": 5},
        "messages": [HumanMessage(content=[make_ref_block("att-1", "image/png")])],
        "flags": {},
        "totals": {},
        "run_logs": [],
    }
    config = {
        "configurable": {
            "model": Model(),
            "image_payload": {"att-1": ImagePayload(att_id="att-1", mime="image/png", data_b64="cG5n")},
            "current_image_ids": {"att-1"},
            "vision": True,
            "image_capability_state": VisionCapability.UNKNOWN.value,
            "image_capability_key": key,
        }
    }

    with pytest.raises(type(error)):
        await agent_execute_module.agent_execute_node(state, config)
    assert resolver_calls == []
