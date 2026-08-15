"""T2 EmbeddingService 测试（httpx MockTransport 注入，不碰外网）。

覆盖：请求体正确、批量、429/5xx 重试、401 快速失败、维度校验。
"""
from __future__ import annotations

import httpx
import pytest

from app.core.errors import AppError
from app.services.embeddings import EmbeddingService
from app.storage.models.kb import EMBED_DIM


def _service(handler) -> EmbeddingService:
    transport = httpx.MockTransport(handler)
    return EmbeddingService(
        model="Qwen/Qwen3-Embedding-0.6B",
        base_url="https://api.siliconflow.cn/v1",
        api_key="test-key",
        transport=transport,
    )


def _ok_response(n: int = 1, dim: int | None = None) -> dict:
    dim = dim or EMBED_DIM
    return {
        "data": [{"embedding": [0.1] * dim, "index": i} for i in range(n)],
        "model": "Qwen/Qwen3-Embedding-0.6B",
        "usage": {"total_tokens": n},
    }


async def test_embed_query_request_shape():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode()
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_ok_response())

    svc = _service(handler)
    vec = await svc.embed_query("用户问题")
    assert len(vec) == EMBED_DIM
    assert captured["url"].endswith("/embeddings")
    assert '"input": "用户问题"' in captured["body"]
    assert '"model": "Qwen/Qwen3-Embedding-0.6B"' in captured["body"]
    assert captured["auth"] == "Bearer test-key"


async def test_embed_documents_batch_request():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(200, json=_ok_response(n=2))

    svc = _service(handler)
    vecs = await svc.embed_documents(["片段1", "片段2"])
    assert len(vecs) == 2
    assert all(len(v) == EMBED_DIM for v in vecs)
    assert '"input": ["片段1", "片段2"]' in captured["body"]


async def test_retry_on_429():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=_ok_response())

    svc = _service(handler)
    vec = await svc.embed_query("x")
    assert len(vec) == EMBED_DIM
    assert calls["n"] == 3  # 重试 2 次后成功


async def test_retry_on_5xx():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "upstream"})
        return httpx.Response(200, json=_ok_response())

    svc = _service(handler)
    await svc.embed_query("x")
    assert calls["n"] == 3


async def test_401_fails_fast_no_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    svc = _service(handler)
    with pytest.raises(AppError) as exc:
        await svc.embed_query("x")
    assert exc.value.code == 50001
    assert calls["n"] == 1  # 不重试


async def test_dimension_mismatch_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_response(dim=512))  # 维度错误

    svc = _service(handler)
    with pytest.raises(AppError) as exc:
        await svc.embed_query("x")
    assert exc.value.code == 50001
    assert "维度" in exc.value.message


async def test_missing_api_key_raises():
    svc = EmbeddingService(
        model="Qwen/Qwen3-Embedding-0.6B",
        base_url="https://api.siliconflow.cn/v1",
        api_key="",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_ok_response())),
    )
    with pytest.raises(AppError) as exc:
        await svc.embed_query("x")
    assert exc.value.code == 50001
