"""A2 analyze_image 工具测试（DB-backed）：注册默认关、文本提取、参数校验、附件不存在、桥缺失降级。"""
from __future__ import annotations

import uuid

import pytest

from app.core.config import get_settings
from app.storage.file.store import get_store
from app.storage.models import Attachment, User
from app.tools import executor
from app.tools.builtin import register_builtin_tools
from app.tools.registry import get


@pytest.fixture
async def analyze_fixture(clean_mcp_specs, tmp_path, monkeypatch):
    register_builtin_tools()
    s = get_settings()
    monkeypatch.setattr(s, "upload_dir", str(tmp_path))
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"ai_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        fpath = tmp_path / f"note-{uid}.txt"
        fpath.write_text("这是附件内容", encoding="utf-8")
        att = Attachment(
            user_id=user.id, filename="note.txt", content_type="text/plain", size_bytes=fpath.stat().st_size,
            storage_path=str(fpath), status="uploaded",
        )
        session.add(att)
        await session.flush()
        att_id = att.id
        await session.commit()
    yield user, att_id


async def test_registered_default_off(analyze_fixture):
    spec = get("tl_analyze_image")
    assert spec is not None
    assert spec.enabled is False  # 默认关闭
    assert spec.builtin is True
    aci = spec.aci()
    assert "attachment_id" in aci["function"]["parameters"]["properties"]


async def test_handler_text_extraction(analyze_fixture):
    user, att_id = analyze_fixture
    spec = get("tl_analyze_image")
    result = await executor.execute(spec, {"attachment_id": str(att_id)})
    assert result.ok is True
    assert result.output["text"] == "这是附件内容"
    assert result.output["type"] == "document"
    assert result.output["attachment_id"] == str(att_id)


async def test_missing_param_validation(analyze_fixture):
    spec = get("tl_analyze_image")
    result = await executor.execute(spec, {})  # 缺 attachment_id
    assert result.ok is False
    assert "参数校验失败" in result.error


async def test_attachment_not_found(analyze_fixture):
    spec = get("tl_analyze_image")
    result = await executor.execute(spec, {"attachment_id": str(uuid.uuid4())})
    assert result.ok is True  # 降级结果不报错
    assert "error" in result.output
    assert "不存在" in result.output["error"]


async def test_no_bridge_degrades(analyze_fixture):
    """存储不可用（store 被摘除）→ 降级 error 结果，不击穿工具调用。"""
    from app.storage.file.store import get_store, set_store

    user, att_id = analyze_fixture
    original = get_store()
    set_store(None)
    try:
        result = await executor.execute(get("tl_analyze_image"), {"attachment_id": str(att_id)})
        assert result.ok is True
        assert "error" in result.output
    finally:
        set_store(original)
