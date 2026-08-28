"""多模态消息适配核心（2026-08-27，docs 01 §6 多模态）。

设计：b64 载荷与消息分离——HumanMessage 里只放轻量 image_ref 引用块（几十字节 dict），
真正的 base64 进 graph_config.configurable（configurable 不落 checkpoint）。JsonFileSaver
每个 super-step 全量快照 messages：b64 直进 state 会让每轮 checkpoint 膨胀几十 MB 且
历史图片跨轮永久重放计费；引用块方案顺带达成「跨轮媒体不回放」的主流行为（token 成本有界）。

渲染时（build_context → render_view）把当前轮 ref 水合为 LangChain 标准图像块：
{"type":"image","source_type":"base64","data":...,"mime_type":...}
——该格式经 langchain-openai _format_message_content 直达 OpenAI payload（已验证）。
其余一切 ref（历史轮 / 非 vision / 缺 payload）→ 文本标记降级。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage

from app.storage.attachment_analysis import _IMAGE_TYPES

# state 内的轻量图片引用块（不进 API 的中间形态；b64 绝不进 message/checkpoint）
REF_TYPE = "image_ref"
# 当前轮 ref 水合后的 LangChain 标准图像块类型名
IMAGE_BLOCK_TYPE = "image"


@dataclass
class ImagePayload:
    """一张图片的读盘+b64 结果（只存在于 graph_config.configurable，进程内存）。"""

    att_id: str
    mime: str
    data_b64: str


def make_ref_block(att_id: str, mime: str) -> dict[str, str]:
    return {"type": REF_TYPE, "attachment_id": att_id, "mime_type": mime}


def is_ref_block(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == REF_TYPE


def is_image_mime(mime: str | None) -> bool:
    """mime 白名单复用 attachment_analysis._IMAGE_TYPES（png/jpeg/webp/gif，单一事实源）。"""
    return (mime or "").lower() in _IMAGE_TYPES


# 预算裁剪：返回 (保留 payloads, 被剔数量)。按序累计，装不下的从超界那张起全剔（保前序）
def fit_budget(payloads: list[ImagePayload], budget_mb: int) -> tuple[list[ImagePayload], int]:
    if budget_mb <= 0:
        return [], len(payloads)
    limit = budget_mb * 1024 * 1024
    kept: list[ImagePayload] = []
    used = 0
    for p in payloads:
        size = len(p.data_b64) * 3 // 4  # b64 还原为原始字节数
        if used + size > limit and kept:
            break
        if size > limit:  # 单张即超限 → 剔这张继续看后面的
            continue
        kept.append(p)
        used += size
    return kept, len(payloads) - len(kept)


def no_vision_note(model: str, n_images: int, n_dropped: int = 0) -> str:
    """非视觉模型收图的注记（内联于同一条 user 消息前缀，绝不放独立 SystemMessage——避免污染后续轮前缀）。"""
    note = (
        f"（系统提示：当前模型 {model} 不支持读取图片，用户本次发送了 {n_images} 张图片已被忽略；"
        "请基于文字作答，如需看图请建议用户切换支持视觉的模型。）"
    )
    if n_dropped > 0:
        note += f"另有 {n_dropped} 张图片未能送达；其中 {n_dropped} 张图片因超过单轮大小预算或读取失败。"
    return note


def vision_drop_note(n_dropped: int) -> str:
    """vision 模型但部分图被预算裁剪的注记（拼在文本块前）。"""
    return f"（系统提示：用户本次发送的 {n_dropped} 张图片未能送达；其中可能因超过单轮大小预算或读取失败。）"


def human_message_with_images(
    text: str,
    refs: list[dict[str, str]],
    vision: bool,
    *,
    model: str = "",
    n_images: int = 0,
    n_dropped: int = 0,
) -> HumanMessage:
    """三分支构造初始用户消息（唯一构造收口）：

    ① vision=True 有 ref → content=[ref..., text 块]（图片在前文本在后，主流惯例；ref 待 build_context 水合）
    ② vision=False 有 ref → str 注记前缀 + 原文（ref 全丢弃，本轮不做 OCR——用户拍板）
    ③ 无 ref → HumanMessage(content=text)（与无多模态时的现状逐字节相同，零回归锚点）
    """
    candidate_count = n_images or len(refs)
    if not refs and candidate_count == 0:
        return HumanMessage(content=text)
    if not vision:
        prefix = no_vision_note(model or "当前模型", candidate_count, n_dropped)
        return HumanMessage(content=f"{prefix}\n\n{text}")
    if not refs:
        return HumanMessage(content=f"{vision_drop_note(n_dropped or candidate_count)}\n\n{text}")
    blocks: list[dict[str, Any]] = [dict(r) for r in refs]
    text_block = {"type": "text", "text": f"{vision_drop_note(n_dropped)}{text}" if n_dropped else text}
    blocks.append(text_block)
    return HumanMessage(content=blocks)


# 文本标记（历史轮/缺 payload/非 vision 兜底）：让模型知道这里曾有图但不占体积
def _ref_fallback_text(ref: dict[str, str]) -> dict[str, str]:
    return {"type": "text", "text": f"[图片已省略：attachment {ref.get('attachment_id', '?')}]"}


def render_message_content(content: Any, *, index: dict[str, ImagePayload], current_ids: set[str], vision: bool) -> Any:
    """state 消息 content → 模型可见 content（幂等：str 纯文本直通；仅含 ref 的 list 才改写）。

    - vision 且 ref ∈ current_ids 且 payload 在 → 标准图像块（source_type:"base64"）
    - 其余一切 ref → 文本标记降级（历史轮不回放媒体，跨轮成本有界）
    """
    if not isinstance(content, list):
        return content
    has_ref = any(is_ref_block(b) for b in content)
    if not has_ref:
        return content
    out: list[dict[str, Any]] = []
    for b in content:
        if not is_ref_block(b):
            out.append(b)
            continue
        att_id = b.get("attachment_id", "")
        p = index.get(att_id)
        if vision and att_id in current_ids and p is not None:
            out.append({"type": IMAGE_BLOCK_TYPE, "source_type": "base64", "data": p.data_b64, "mime_type": p.mime})
        else:
            out.append(_ref_fallback_text(b))
    # 若水合后只剩文本（理论上不会：ref 转 fallback 至少留标记），保持 list 结构一致性即可
    return out


def encode_image(data: bytes) -> str:
    """bytes → base64 字符串（编码统一收口，禁止散落手拼 data URL）。"""
    return base64.b64encode(data).decode("ascii")
