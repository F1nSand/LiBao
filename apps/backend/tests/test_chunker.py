"""T2 分块器测试：字符滑窗 512/64、中文/短文本/空/overlap 边界。"""
from __future__ import annotations

from app.services.chunker import chunk_text


def test_default_chunking_chinese():
    text = "今天的天气很好，我们一起去公园散步吧。" * 30  # ~480 字
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    assert all(len(c) <= 512 for c in chunks)
    # 滑窗 overlap：下一块起点 = 起点 + 512 - 64
    assert chunks[0][-64:] == chunks[1][:64] or len(chunks) == 1


def test_short_text_single_chunk():
    assert chunk_text("你好") == ["你好"]


def test_empty_and_whitespace():
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_overlap_ge_size_normalized():
    # overlap >= chunk_size → 归一化为 chunk_size - 1（不无限回退）
    text = "a" * 1000
    chunks = chunk_text(text, chunk_size=100, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_custom_size_and_overlap():
    text = "abcdefghij" * 100  # 1000 字符
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    # 期望块数：ceil((1000 - 200) / (200 - 40)) + 1 = ceil(800/160) + 1 = 6
    assert len(chunks) == 6
    assert chunks[1].startswith(chunks[0][-40:])


def test_chunk_boundary_strips_whitespace():
    text = "  第一块内容" + "x" * 500 + "   "
    chunks = chunk_text(text)
    assert chunks[0] == chunks[0].strip()
