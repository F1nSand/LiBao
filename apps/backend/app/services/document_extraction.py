"""确定性的附件正文抽取与分块。

抽取器只处理字节，不访问数据库或 LLM。解析失败统一转换为
``DocumentExtractionError``，正文上限和分块边界在这里收口，调用方再决定如何把结果
投影到当前模型请求。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

MAX_EXTRACTED_CHARS = 50_000
_PDF_MIME = "application/pdf"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".json", ".yaml",
    ".yml", ".toml", ".xml", ".html", ".htm", ".css", ".scss", ".sql", ".sh", ".bat", ".cmd",
    ".ps1", ".csv", ".log",
}


class DocumentExtractionError(ValueError):
    """附件正文无法按声明格式解析。"""


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    kind: str
    truncated: bool = False
    warning: str | None = None


def _text_units(data: bytes) -> list[tuple[str, str]]:
    return [("", data.decode("utf-8-sig", errors="replace"))]


def _pdf_units(data: bytes) -> list[tuple[str, str]]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        units: list[tuple[str, str]] = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                units.append((f"第{number}页", text))
        return units
    except Exception as exc:  # noqa: BLE001 - parser-specific exceptions vary by pypdf version
        raise DocumentExtractionError(f"PDF 正文提取失败: {str(exc)[:200]}") from exc


def _docx_units(data: bytes) -> list[tuple[str, str]]:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(io.BytesIO(data))
        units: list[tuple[str, str]] = []
        for child in document.element.body.iterchildren():
            if child.tag.endswith("}p"):
                text = Paragraph(child, document).text
                if text.strip():
                    units.append(("段落", text))
            elif child.tag.endswith("}tbl"):
                table = Table(child, document)
                for row_number, row in enumerate(table.rows, start=1):
                    cells = [cell.text.strip() for cell in row.cells]
                    line = " | ".join(cells).strip()
                    if line:
                        units.append((f"表格第{row_number}行", line))
        return units
    except Exception as exc:  # noqa: BLE001 - parser-specific exceptions vary by python-docx version
        raise DocumentExtractionError(f"DOCX 正文提取失败: {str(exc)[:200]}") from exc


def extract_document_units(data: bytes, *, content_type: str, filename: str = "") -> tuple[str, list[tuple[str, str]]]:
    """返回 kind 与带来源标签的正文单元，供上下文层保留来源顺序。"""
    mime = (content_type or "").lower()
    suffix = Path(filename).suffix.lower()
    if suffix == ".doc" or mime == "application/msword":
        raise DocumentExtractionError(".doc 格式不支持，请转换为 DOCX")
    if mime == _PDF_MIME or suffix == ".pdf":
        return "pdf", _pdf_units(data)
    if mime == _DOCX_MIME or suffix == ".docx":
        return "docx", _docx_units(data)
    if mime.startswith("text/") or suffix in _TEXT_SUFFIXES:
        return "text", _text_units(data)
    if b"\x00" in data:
        raise DocumentExtractionError("二进制文件不支持正文提取")
    raise DocumentExtractionError("文件类型不支持正文提取")


def _join_units(units: list[tuple[str, str]]) -> str:
    blocks: list[str] = []
    for label, text in units:
        clean = text.strip()
        if not clean:
            continue
        blocks.append(f"[{label}]\n{clean}" if label else clean)
    return "\n\n".join(blocks)


def extract_document(data: bytes, *, content_type: str, filename: str) -> ExtractedDocument:
    """抽取并限制正文，所有边界均按 Unicode 字符处理。"""
    kind, units = extract_document_units(data, content_type=content_type, filename=filename)
    text = _join_units(units)
    warning: str | None = None
    if kind == "pdf" and not text:
        warning = "未提取到文本，文件可能为扫描件；当前未执行 OCR"
    truncated = len(text) > MAX_EXTRACTED_CHARS
    if truncated:
        text = text[:MAX_EXTRACTED_CHARS]
        warning = warning or f"正文超过 {MAX_EXTRACTED_CHARS} 字符，已截断"
    return ExtractedDocument(text=text, kind=kind, truncated=truncated, warning=warning)


def chunk_text(text: str, *, size: int = 1_200, overlap: int = 120) -> tuple[str, ...]:
    """按固定 Unicode 字符窗口分块，重复调用结果完全确定。"""
    if not text:
        return ()
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("size 必须大于 0，且 overlap 必须满足 0 <= overlap < size")
    if len(text) <= size:
        return (text,)
    step = size - overlap
    return tuple(text[start : start + size] for start in range(0, len(text), step))
