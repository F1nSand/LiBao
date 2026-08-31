"""模型请求上下文的轻量、脱敏规模观测。

该模块不决定模型上下文窗口，也不修改发送给 provider 的消息；它只统计请求规模，
以便区分上下文超限和流式连接中断。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage


def _estimate_text_tokens(text: str) -> int:
    ascii_count = sum(ch.isascii() and (ch.isalnum() or ch.isspace() or ch in " punctuation") for ch in text)
    cjk_count = sum(
        "\u3400" <= ch <= "\u4dbf" or "\u4e00" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff"
        for ch in text
    )
    other_count = max(0, len(text) - ascii_count - cjk_count)
    return math.ceil(ascii_count / 4) + cjk_count + math.ceil(other_count / 2)


def _block_text(block: Any) -> tuple[str, int, int]:
    """返回 (可计文本, 图片数, 文档字符数)，永不返回图片 data/url 内容。"""

    if isinstance(block, str):
        return block, 0, 0
    if not isinstance(block, dict):
        return str(block), 0, 0
    block_type = str(block.get("type") or "")
    if block_type in {"image", "image_url", "input_image"}:
        return "", 1, 0
    if block_type in {"document_ref", "document", "file_ref"}:
        text = block.get("text") or block.get("name") or block.get("path") or ""
        return str(text), 0, len(str(text))
    if block_type == "text":
        return str(block.get("text") or ""), 0, 0
    # 未知 block 只读取明确的 text 字段，避免把嵌套图片/url 序列化到指标。
    return str(block.get("text") or ""), 0, 0


def _message_metrics(message: Any) -> tuple[str, int, int]:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        parts = [_block_text(block) for block in content]
        return "".join(p[0] for p in parts), sum(p[1] for p in parts), sum(p[2] for p in parts)
    text, images, documents = _block_text(content)
    return text, images, documents


def measure_context(messages: Sequence[BaseMessage], tools: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """生成稳定的脱敏 context metrics；estimated_prompt_tokens 是启发式估算值。"""

    text_chars = 0
    text_for_estimate: list[str] = []
    image_count = 0
    document_chars = 0
    for message in messages:
        text, images, documents = _message_metrics(message)
        text_chars += len(text)
        text_for_estimate.append(text)
        image_count += images
        document_chars += documents

    tool_schema_chars = 0
    for tool in tools:
        # schema 结构计数即可，不保留 description/参数值到 metrics。
        tool_schema_chars += len(str(tool.get("function", {}).get("name", "")))
        tool_schema_chars += len(str(tool.get("function", {}).get("description", "")))
        tool_schema_chars += len(str(tool.get("function", {}).get("parameters", "")))
    tool_text = "".join(
        str(tool.get("function", {}).get(field, ""))
        for tool in tools
        for field in ("name", "description", "parameters")
    )
    estimated_prompt_tokens = _estimate_text_tokens("".join(text_for_estimate)) + _estimate_text_tokens(tool_text)
    return {
        "message_count": len(messages),
        "text_chars": text_chars,
        "tool_schema_chars": tool_schema_chars,
        "image_count": image_count,
        "document_chars": document_chars,
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "estimated": True,
        "estimate_method": "unicode_heuristic_v1",
    }
