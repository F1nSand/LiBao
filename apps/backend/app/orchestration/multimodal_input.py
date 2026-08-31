"""统一的、带所有权校验的图片输入准备流水线。

图片引用进入 graph state，图片 base64 只进入当前运行的 configurable 上下文。
该模块是 chat 与 Task 共用的唯一读盘入口：非视觉模型只查询附件元数据，绝不读取文件。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.model_capabilities import ModelCapabilityKey, VisionCapability, get_model_capability_resolver
from app.core.multimodal import ImagePayload, encode_image, fit_budget, is_image_mime, make_ref_block
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
    vision: bool = True  # 旧调用方兼容字段；能力三态以 capability 为准
    capability: VisionCapability = VisionCapability.UNKNOWN
    capability_key: ModelCapabilityKey | None = None


async def prepare_image_input(
    db: Any,
    *,
    user_id: uuid.UUID,
    attachment_ids: list[str],
    effective_model: str,
    effective_base_url: str | None = None,
) -> PreparedImageInput:
    """按请求顺序准备当前轮图片，并在读取前完成附件所有权校验。

    不存在、软删或他人附件会被忽略；它们不会成为可见图片候选。已归属的图片若读盘失败，
    计入 omission，保证模型能收到准确的降级提示。只有能力解析明确为 unsupported 时才跳过读盘；
    unknown 与 supported 均按真实请求准备图片。
    """
    settings = get_settings()
    capability_key = ModelCapabilityKey(
        effective_base_url if effective_base_url is not None else settings.llm_base_url,
        effective_model,
    )
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
    if candidate_count == 0:
        # Plain turns must still return a lightweight prepared object so callers can clear
        # historical refs, but they should not trigger metadata discovery or catalog work.
        return PreparedImageInput(
            image_refs=(),
            image_payload={},
            current_image_ids=frozenset(),
            candidate_count=0,
            omitted_count=0,
            vision=False,
            capability=VisionCapability.UNKNOWN,
            capability_key=capability_key,
        )
    resolver = get_model_capability_resolver()
    capability = await resolver.resolve_vision(capability_key, settings.llm_api_key or None)
    if capability.state is VisionCapability.UNSUPPORTED:
        return PreparedImageInput(
            image_refs=(),
            image_payload={},
            current_image_ids=frozenset(),
            candidate_count=candidate_count,
            omitted_count=0,
            vision=False,
            capability=capability.state,
            capability_key=capability.key,
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

    kept, _ = fit_budget(payloads, settings.image_total_budget_mb)
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
        capability=capability.state,
        capability_key=capability.key,
    )


def image_config(prepared: PreparedImageInput | None, *, force_context: bool = False) -> dict[str, Any]:
    """转为 graph configurable 图片上下文；force 只保证空上下文显式存在。"""
    if prepared is None:
        if not force_context:
            return {}
        return {"image_payload": {}, "current_image_ids": set(), "vision": False}
    if prepared.candidate_count == 0:
        if not force_context:
            return {}
        return {"image_payload": {}, "current_image_ids": set(), "vision": False}
    return {
        "image_payload": prepared.image_payload,
        "current_image_ids": set(prepared.current_image_ids),
        "vision": prepared.vision,
        "image_capability_state": prepared.capability.value,
        "image_capability_key": prepared.capability_key,
    }
