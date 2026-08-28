"""附件内容抽取缓存（docs 01 §7.6 / docs 04 §3.7）。存储层纯内容处理。

解析结果只服务于当前轮上下文准备或诊断接口，不表示模型已经读取；服务层后台链与聊天发送复用此函数。
"""

from __future__ import annotations

from pathlib import Path

from app.storage.models.attachment import Attachment

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_TEXT_TYPES = {"text/plain", "text/markdown"}
_DOCUMENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ALLOWED = _IMAGE_TYPES | _TEXT_TYPES | _DOCUMENT_TYPES
_TEXT_MAX = 200_000  # 内部抽取缓存上限；模型上下文另由 document_context 预算
# 持久化到 Attachment.analysis，确保升级正文抽取策略后旧的 metadata-only
# 缓存不会被误认为 ready 并永久跳过重抽。
EXTRACTOR_VERSION = "document-context-v2"
EXTRACTION_STRATEGY = "utf8-pypdf-python-docx-v1"


def _analysis_meta(kind: str, **values: object) -> dict:
    return {
        "type": kind,
        "extractor_version": EXTRACTOR_VERSION,
        "extraction_strategy": EXTRACTION_STRATEGY,
        **values,
    }


def analyze_content(att: Attachment) -> dict:
    """按类型生成内部抽取缓存；状态不代表模型已经读取附件。"""
    ct = att.content_type
    if ct in _IMAGE_TYPES:
        return _analysis_meta(
            "image",
            text="无法分析: 当前部署无视觉模型（VLM 为 M4 接缝）",
            reason="no_vision_model",
        )
    if ct in _TEXT_TYPES or ct in _DOCUMENT_TYPES:
        try:
            # 延迟导入避免 storage → orchestration 的模块初始化环；聊天发送和后台预热
            # 复用同一抽取器，正文不会被写入 checkpoint。
            from app.orchestration.document_context import extract_document_units

            units = extract_document_units(Path(att.storage_path).read_bytes(), ct, att.filename)
            blocks = []
            for label, text in units:
                text = text.strip()
                if text:
                    blocks.append(f"[{label}]\n{text}" if label else text)
            text = "\n\n".join(blocks)[:_TEXT_MAX]
            return _analysis_meta("document", text=text, source_units=len(units))
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"文本提取失败: {exc}") from exc
        except Exception as exc:  # noqa: BLE001  损坏 PDF/DOCX 保留诊断信息
            return _analysis_meta(
                "document",
                text=None,
                summary={"filename": att.filename, "size": att.size_bytes},
                reason=f"文档正文提取失败: {str(exc)[:200]}",
            )
    raise ValueError("文件类型不支持正文解析")
