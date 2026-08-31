"""分块器（《02》后端设计 §9.1）。纯 Python 字符滑窗，无 jieba 依赖（中文按字符切，MVP 接缝）。

窗口规则：每块 chunk_size 字符，下一块起点 = 起点 + (chunk_size - overlap)；
overlap ≥ chunk_size 时归一化为 chunk_size - 1（防无限回退）。
"""

from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if overlap >= chunk_size:
        overlap = chunk_size - 1
    if overlap < 0:
        overlap = 0
    step = chunk_size - overlap
    if step <= 0:  # 防御：chunk_size=0 或 overlap=chunk_size-1 后 step 仍 ≤0（text 已在上方保证非空）
        return [text]
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= n:
            break
        start += step
    return chunks
