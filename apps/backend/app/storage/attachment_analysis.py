"""附件内容抽取缓存（《02》后端设计 §7.6 / 《02》数据模型 §3.7）。存储层纯内容处理。

解析结果只服务于当前轮上下文准备或诊断接口，不表示模型已经读取；图片理解由发送时的模型能力协商负责。
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
_TEXT_MAX = 50_000  # 内部抽取缓存上限；模型上下文另由 document_context 预算
# 持久化到 Attachment.analysis，确保升级正文抽取策略后旧的 metadata-only
# 缓存不会被误认为 ready 并永久跳过重抽。
EXTRACTOR_VERSION = "document-context-v3"
EXTRACTION_STRATEGY = "utf8-replace-pypdf-python-docx-v2"


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
        # 上传分析不调用视觉模型。图片理解发生在发送消息时，由运行期能力协商决定；
        # 这里仅把“尚未分析”作为中性状态，不能把一次上传后台任务误报成部署能力结论。
        return _analysis_meta(
            "image",
            text=None,
            reason="analysis_on_send",
        )
    if ct in _TEXT_TYPES or ct in _DOCUMENT_TYPES:
        try:
            from app.services.document_extraction import extract_document

            extracted = extract_document(Path(att.storage_path).read_bytes(), content_type=ct, filename=att.filename)
            result = _analysis_meta(
                "document",
                text=extracted.text or None,
                truncated=extracted.truncated,
            )
            if extracted.warning:
                result["reason"] = extracted.warning
            return result
        except OSError as exc:
            raise ValueError(f"文本提取失败: {exc}") from exc
        except Exception as exc:  # noqa: BLE001  损坏 PDF/DOCX 保留诊断信息
            return _analysis_meta(
                "document",
                text=None,
                summary={"filename": att.filename, "size": att.size_bytes},
                reason=f"文档正文提取失败: {str(exc)[:200]}",
            )
    raise ValueError("文件类型不支持正文解析")
