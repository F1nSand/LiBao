"""附件/工作区正文输入的兼容门面。

聊天主链使用 :mod:`document_context` 保存 ``document_ref`` 与当前轮索引；本模块提供
计划中约定的窄接口，供轻量调用方和测试复用，不把正文写入消息或 checkpoint。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.errors import ERR_WORKSPACE_FILE_REF_INVALID, AppError
from app.orchestration.document_context import (
    WORKSPACE_READ_LIMIT,
    PreparedDocumentContext,
    prepare_document_context,
    render_document_content,
    select_source_text,
)
from app.services.document_extraction import extract_document
from app.services.workspace import read_file_ref_bytes, resolve_file_ref_path


@dataclass(frozen=True, slots=True)
class PreparedDocumentInput:
    """当前轮文档输入；``context`` 仅为进程内渲染索引，不参与持久化。"""

    context_text: str
    attachment_refs: tuple[dict[str, Any], ...]
    omitted: tuple[str, ...]
    context: PreparedDocumentContext | None = field(default=None, repr=False, compare=False)


def _from_context(context: PreparedDocumentContext) -> PreparedDocumentInput:
    rendered = render_document_content(
        list(context.refs), index=context.index, current_ids=set(context.index)
    )
    texts = [str(block.get("text", "")) for block in rendered if isinstance(block, dict)]
    omitted = tuple(text for text in texts if "内容不可用" in text)
    return PreparedDocumentInput(
        context_text="\n\n".join(text for text in texts if text),
        attachment_refs=tuple(context.refs),
        omitted=omitted,
        context=context,
    )


async def prepare_document_input(
    db: Any,
    *,
    user_id: UUID,
    attachment_ids: list[str],
    query: str,
) -> PreparedDocumentInput:
    """准备上传文档正文，沿用带 owner 校验和固定预算的主上下文实现。"""
    return _from_context(
        await prepare_document_context(
            db,
            user_id=user_id,
            user_content=query,
            attachment_ids=attachment_ids,
        )
    )


def document_config(
    prepared: PreparedDocumentInput | None, *, force_context: bool = False
) -> dict[str, Any]:
    """把正文索引放入当前 graph configurable；空/恢复上下文可显式清理历史 ref。"""
    if prepared is None:
        return {"document_context": {"index": {}, "current_ids": set()}} if force_context else {}
    context = prepared.context
    if context is None:
        return {"document_context": {"index": {}, "current_ids": set()}} if force_context else {}
    return {
        "document_context": {
            "index": context.index,
            "current_ids": set(context.index),
        }
    }


async def prepare_workspace_file_input(
    *, workspace_root: str,
    file_refs: list[Any],
    query: str,
) -> PreparedDocumentInput:
    """读取工作区相对文件并生成来源标记；路径错误统一为 40015。"""
    refs: list[dict[str, str]] = []
    index: dict[str, dict[str, str]] = {}
    omitted: list[str] = []
    for raw in file_refs:
        path = raw.path if hasattr(raw, "path") else raw.get("path") if isinstance(raw, dict) else raw
        try:
            canonical, _ = resolve_file_ref_path(workspace_root, str(path))
        except AppError as exc:
            if exc.code == ERR_WORKSPACE_FILE_REF_INVALID:
                raise
            omitted.append(str(path))
            continue
        try:
            data = await asyncio.to_thread(read_file_ref_bytes, workspace_root, canonical, WORKSPACE_READ_LIMIT)
            extracted = extract_document(data, content_type="", filename=canonical)
            ref = {
                "type": "document_ref",
                "ref_id": f"workspace:{canonical}",
                "source_id": f"workspace:{canonical}",
                "kind": "workspace",
                "display_name": Path(canonical).name,
                "path": canonical,
            }
            refs.append(ref)
            index[ref["ref_id"]] = {
                "display_name": ref["display_name"],
                "kind": "workspace",
                "path": canonical,
                "text": select_source_text(extracted.text, query, limit=12_000),
            }
            if extracted.warning:
                index[ref["ref_id"]]["omitted_reason"] = extracted.warning
        except Exception:  # noqa: BLE001 - per-source failure does not hide other refs
            omitted.append(str(path))
    context = PreparedDocumentContext(tuple(refs), index)
    result = _from_context(context)
    return PreparedDocumentInput(result.context_text, result.attachment_refs, tuple(omitted) + result.omitted, context)
