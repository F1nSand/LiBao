"""统一的、带所有权校验的图片输入准备流水线。

图片引用进入 graph state，图片 base64 只进入当前运行的 configurable 上下文。
该模块是 chat 与 Task 共用的唯一读盘入口：非视觉模型只查询附件元数据，绝不读取文件。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.multimodal import ImagePayload, encode_image, fit_budget, is_image_mime, make_ref_block
from app.core.vision import supports_vision
from app.services.attachment import AttachmentService
from app.storage.repositories.attachment import AttachmentRepository


@dataclass(frozen=True, slots=True)
class PreparedImageInput:
    """当前轮图片上下文；refs 轻量可进 state，payload 只应放 configurable。"""

    image_refs: tuple[dict[str, str], ...]
    image_payload: dict[str, ImagePayload]
    current_image_ids: frozenset[str]
    candidate_count: int
    omitted_count: int
    vision: bool


async def prepare_image_input(
    db: Any,
    *,
    user_id: uuid.UUID,
    attachment_ids: list[str],
    effective_model: str,
) -> PreparedImageInput:
    """按请求顺序准备当前轮图片，并在读取前完成附件所有权校验。

    不存在、软删或他人附件会被忽略；它们不会成为可见图片候选。已归属的图片若读盘失败，
    计入 omission，保证模型能收到准确的降级提示。非视觉模型仍会识别图片候选，但不会读盘。
    """
    vision = supports_vision(effective_model, get_settings().llm_vision_declared)
    repo = AttachmentRepository(db)
    candidates: list[tuple[str, str, Any]] = []

    for raw_id in attachment_ids:
        try:
            attachment_id = uuid.UUID(str(raw_id))
        except (AttributeError, ValueError):
            continue
        row = await repo.get(user_id, attachment_id)
        if row is None or not is_image_mime(getattr(row, "content_type", None)):
            continue
        candidates.append((str(row.id), row.content_type, row))

    candidate_count = len(candidates)
    if not vision:
        return PreparedImageInput(
            image_refs=(),
            image_payload={},
            current_image_ids=frozenset(),
            candidate_count=candidate_count,
            omitted_count=candidate_count,
            vision=False,
        )

    service = AttachmentService()
    payloads: list[ImagePayload] = []
    for attachment_id, mime, row in candidates:
        try:
            data = await service.read_file(row)
        except Exception:
            # 单张图片不可读不应击穿整轮；omitted_count 由 candidate_count - kept_count 统一计算。
            continue
        payloads.append(ImagePayload(att_id=attachment_id, mime=mime, data_b64=encode_image(data)))

    kept, _ = fit_budget(payloads, get_settings().image_total_budget_mb)
    image_payload = {payload.att_id: payload for payload in kept}
    current_image_ids = frozenset(image_payload)
    image_refs = tuple(make_ref_block(payload.att_id, payload.mime) for payload in kept)
    return PreparedImageInput(
        image_refs=image_refs,
        image_payload=image_payload,
        current_image_ids=current_image_ids,
        candidate_count=candidate_count,
        omitted_count=candidate_count - len(image_refs),
        vision=True,
    )


def image_config(prepared: PreparedImageInput | None, *, force_context: bool = False) -> dict[str, Any]:
    """转为 graph configurable 图片上下文；无图路径不新增 configurable 键。"""
    if force_context:
        return {"image_payload": {}, "current_image_ids": set(), "vision": False}
    if prepared is None or prepared.candidate_count == 0:
        return {}
    return {
        "image_payload": prepared.image_payload,
        "current_image_ids": set(prepared.current_image_ids),
        "vision": prepared.vision,
    }
