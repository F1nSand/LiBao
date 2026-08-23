"""消息文本提取（独立模块：stream_core/memory 系共用，避免导入环）。"""

from __future__ import annotations

from typing import Any


def message_text(content: Any) -> str:
    """消息文本提取（兼容 str 或 content blocks 列表；跳过 thinking 块，
    保留裸字符串块——DeepSeek v4-flash 会把最终输出放在末位裸 str 块）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") != "thinking":
                parts.append(b.get("text", ""))
        return "".join(parts)
    return str(content)
