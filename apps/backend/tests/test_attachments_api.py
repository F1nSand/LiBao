"""T9 附件测试（DB-backed，tmp_path 指 upload_dir）：上传落盘、错误码、分析状态机、
图片降级/txt 提取/pdf metadata、DELETE 级联、非本人 40403。
"""
from __future__ import annotations

import uuid

import pytest

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.attachment import AttachmentService, analyze_attachment
from app.services.serializers import serialize_attachment
from app.storage.attachment_analysis import EXTRACTION_STRATEGY, EXTRACTOR_VERSION
from app.storage.file.store import get_store
from app.storage.models import Attachment, User


@pytest.fixture
async def att_fixture(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "upload_dir", str(tmp_path))
    # 禁自动分析链（测试手动调 analyze_attachment 控制状态机）
    monkeypatch.setattr("app.services.attachment._spawn_analyze", lambda att_id: None)
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"att_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        other = User(
            username=f"att2_{uid}", password_hash="hashed", name="T2", role="admin", org_id=uuid.UUID(int=0)
        )
        session.add(other)
        await session.commit()
    yield user, other, tmp_path


async def test_upload_persists_and_returns(att_fixture):
    user, other, tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        att = await svc.save_upload(session, user, "a.txt", "text/plain", "你好世界".encode())
        assert att.status == "uploaded"
        assert att.size_bytes == len("你好世界".encode())
        # 落盘
        path = tmp / str(att.id)
        assert path.read_bytes() == "你好世界".encode()
        # GET 二进制一致
        data = await svc.read_file(att)
        assert data == "你好世界".encode()


async def test_upload_type_not_allowed_40012(att_fixture):
    user, other, tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await svc.save_upload(session, user, "x.exe", "application/x-msdownload", b"MZ")
        assert exc.value.code == 40012


async def test_upload_too_large_40011(att_fixture, monkeypatch):
    user, other, tmp = att_fixture
    s = get_settings()
    monkeypatch.setattr(s, "max_upload_mb", 1)  # 1MB
    svc = AttachmentService()
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await svc.save_upload(session, user, "big.txt", "text/plain", b"x" * (1024 * 1024 + 1))
        assert exc.value.code == 40011


async def test_analyze_image_is_neutral_until_send(att_fixture):
    user, other, tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        att = await svc.save_upload(session, user, "pic.png", "image/png", b"\x89PNG")
        att_id = att.id
    await analyze_attachment(att_id)
    async with get_store().session() as session:
        att = await svc.get_attachment(session, user, att_id)
        assert att.status == "ready"  # 降级是完成态，不是 failed
        assert att.analysis["type"] == "image"
        assert att.analysis["reason"] == "analysis_on_send"
        assert att.analysis["text"] is None


async def test_analyze_txt_extracts(att_fixture):
    user, other, tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        att = await svc.save_upload(session, user, "note.txt", "text/plain", "这是笔记内容".encode())
        att_id = att.id
    await analyze_attachment(att_id)
    async with get_store().session() as session:
        att = await svc.get_attachment(session, user, att_id)
        assert att.status == "ready"
        assert att.analysis["text"] == "这是笔记内容"
        assert att.analysis["extractor_version"] == EXTRACTOR_VERSION
        assert att.analysis["extraction_strategy"] == EXTRACTION_STRATEGY


async def test_legacy_ready_analysis_is_recomputed(att_fixture, monkeypatch):
    """旧的 metadata-only ready 缓存不能阻止新正文解析策略生效。"""
    user, _other, _tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        att = await svc.save_upload(session, user, "legacy.txt", "text/plain", b"new text")
        att.status = "ready"
        att.analysis = {"type": "document", "summary": {"filename": "legacy.txt"}}
        await session.commit()
        called = False

        def fresh_analysis(_att):
            nonlocal called
            called = True
            return {
                "type": "document",
                "text": "new text",
                "extractor_version": EXTRACTOR_VERSION,
                "extraction_strategy": EXTRACTION_STRATEGY,
            }

        monkeypatch.setattr("app.services.attachment.analyze_content", fresh_analysis)
        result = await svc.ensure_extracted(session, att)
        assert called
        assert result["text"] == "new text"
        assert result["extractor_version"] == EXTRACTOR_VERSION


async def test_analyze_pdf_unreadable_is_failed(att_fixture):
    user, other, tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        att = await svc.save_upload(session, user, "doc.pdf", "application/pdf", b"%PDF-1.4")
        att_id = att.id
    await analyze_attachment(att_id)
    async with get_store().session() as session:
        att = await svc.get_attachment(session, user, att_id)
        assert att.status == "failed"
        assert att.analysis["text"] is None
        assert "PDF" in att.analysis["reason"] or "文档" in att.analysis["reason"]


async def test_analyze_failed_gives_60004(att_fixture):
    user, other, tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        with pytest.raises(AppError) as upload_exc:
            await svc.save_upload(session, user, "bad.doc", "application/msword", b"\x00\x01")
        assert upload_exc.value.code == 40012
        att = await svc.save_upload(session, user, "bad.pdf", "application/pdf", b"not a pdf")
        att_id = att.id
        await analyze_attachment(att_id)
        with pytest.raises(AppError) as exc:
            await svc.get_analysis(session, user, att_id)
        assert exc.value.code == 60004


async def test_delete_removes_file_and_row(att_fixture):
    user, other, tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        att = await svc.save_upload(session, user, "a.txt", "text/plain", b"x")
        att_id = att.id
        await svc.soft_delete(session, user, att_id)
        with pytest.raises(AppError) as exc:
            await svc.get_attachment(session, user, att_id)
        assert exc.value.code == 40403
        assert not (tmp / str(att_id)).exists()  # 磁盘文件已删


async def test_serialize_attachment_has_attachment_id():
    """S1：serialize_attachment 同时返回 id 与 attachment_id（前端 POST /uploads 消费 attachment_id）。"""
    a = Attachment(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        filename="a.txt",
        content_type="text/plain",
        size_bytes=3,
        storage_path="/tmp/a",
        status="uploaded",
    )
    data = serialize_attachment(a)
    assert data["attachment_id"] == str(a.id)
    assert data["id"] == str(a.id)  # 旧字段保留兼容


async def test_other_user_attachment_40403(att_fixture):
    user, other, tmp = att_fixture
    svc = AttachmentService()
    async with get_store().session() as session:
        att = await svc.save_upload(session, user, "a.txt", "text/plain", b"x")
        with pytest.raises(AppError) as exc:
            await svc.get_attachment(session, other, att.id)  # 他人附件
        assert exc.value.code == 40403
