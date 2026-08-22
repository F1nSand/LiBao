"""附件内容分析（docs 01 §7.6 / docs 04 §3.7）。存储层纯内容处理。

五层约束：工具层（analyze_image）→ 存储层合法，不依赖服务层。服务层后台链同样复用此函数。
"""

from __future__ import annotations

from pathlib import Path

from app.storage.models.attachment import Attachment

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_TEXT_TYPES = {"text/plain", "text/markdown"}
_METADATA_ONLY_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ALLOWED = _IMAGE_TYPES | _TEXT_TYPES | _METADATA_ONLY_TYPES
_TEXT_MAX = 2000  # 提取文本截断


def analyze_content(att: Attachment) -> dict:
    """按类型分析。图片 → 视觉降级（I2）；文本 → 提取；pdf/office → 仅 metadata。"""
    ct = att.content_type
    if ct in _IMAGE_TYPES:
        return {
            "type": "image",
            "text": "无法分析: 当前部署无视觉模型（VLM 为 M4 接缝）",
            "reason": "no_vision_model",
        }
    if ct in _TEXT_TYPES:
        try:
            text = Path(att.storage_path).read_bytes().decode("utf-8")[: _TEXT_MAX]
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"文本提取失败: {exc}") from exc
        return {"type": "document", "text": text}
    # pdf / office：仅元数据（文本提取为 M4 接缝）
    return {
        "type": "document",
        "text": None,
        "summary": {"filename": att.filename, "size": att.size_bytes},
        "reason": "PDF/Office 文本提取为 M4 接缝",
    }
