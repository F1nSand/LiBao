"""Rerank 服务测试（httpx MockTransport 注入，不碰外网）。

覆盖：请求体正确、响应解析降序、score 字段兼容、top_n 截断、无 key 降级。
"""
from __future__ import annotations

import httpx
import pytest

from app.core.errors import AppError
from app.core.rerank import RerankService


def _service(handler) -> RerankService:
    return RerankService(
        model="Qwen/Qwen3-Reranker-0.6B",
        base_url="https://api.siliconflow.cn/v1",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )


async def test_rerank_request_shape_and_parse():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode()
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.5}]},
        )

    svc = _service(handler)
    scored = await svc.rerank("查询", ["doc A", "doc B"], top_n=2)
    assert scored == [(1, 0.9), (0, 0.5)]  # 按 score 降序
    assert captured["url"].endswith("/rerank")
    assert '"model": "Qwen/Qwen3-Reranker-0.6B"' in captured["body"]
    assert '"top_n": 2' in captured["body"]
    assert '"documents": ["doc A", "doc B"]' in captured["body"]
    assert captured["auth"] == "Bearer test-key"


async def test_parse_score_field_fallback():
    """兼容 score 字段（无 relevance_score 的响应变体）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"index": 0, "score": 0.8}, {"index": 1, "score": 0.3}]})

    svc = _service(handler)
    scored = await svc.rerank("q", ["a", "b"], top_n=2)
    assert scored == [(0, 0.8), (1, 0.3)]


async def test_top_n_truncates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"index": i, "relevance_score": 0.9 - i * 0.1} for i in range(5)]}
        )

    svc = _service(handler)
    scored = await svc.rerank("q", [f"d{i}" for i in range(5)], top_n=2)
    assert len(scored) == 2
    assert scored == [(0, 0.9), (1, 0.8)]


async def test_missing_api_key_raises():
    svc = RerankService(
        model="m",
        base_url="https://x",
        api_key="",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    with pytest.raises(AppError) as exc:
        await svc.rerank("q", ["a", "b"], top_n=1)
    assert exc.value.code == 50001


async def test_401_fails_fast_no_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    svc = _service(handler)
    with pytest.raises(AppError):
        await svc.rerank("q", ["a", "b"], top_n=1)
    assert calls["n"] == 1  # 401 不重试
