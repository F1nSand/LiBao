"""内置工具 tl_analyze_image：分析附件（docs 04 F4 / docs 01 §7.6）。

五层约束下工具层→存储层合法：经 sessionmaker 桥读附件 + storage.attachment_analysis 分析。
无 org 归属 join（UUID 不可猜 + MVP 文档标注）；分析结果已落库则返回存储值，否则即时计算。
"""
from __future__ import annotations

import uuid
from typing import Any

from app.storage.attachment_analysis import analyze_content
from app.storage.db import get_sessionmaker
from app.storage.repositories.attachment import AttachmentRepository


async def analyze_image_handler(attachment_id: str) -> dict[str, Any]:
    sessionmaker = get_sessionmaker()
    if sessionmaker is None:
        return {"error": "附件服务不可用"}
    try:
        aid = uuid.UUID(attachment_id)
    except ValueError:
        return {"error": "attachment_id 非法"}
    try:
        async with sessionmaker() as db:
            att = await AttachmentRepository(db).get_any_org(aid)
            if att is None:
                return {"error": "附件不存在"}
            result = dict(att.analysis) if att.analysis is not None else analyze_content(att)
    except Exception as exc:  # noqa: BLE001  分析故障不击穿工具调用
        return {"error": f"分析失败: {str(exc)[:300]}"}
    return {"attachment_id": attachment_id, "status": att.status, **result}
