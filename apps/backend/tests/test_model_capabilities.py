"""运行期视觉能力解析：网关元数据、正向目录提示、三态缓存和拒绝错误分类。"""

from __future__ import annotations

import httpx
import pytest

from app.core.model_capabilities import (
    ModelCapabilityKey,
    ModelCapabilityResolver,
    VisionCapability,
    is_explicit_vision_rejection,
)


def _key(base_url: str = "https://llm.example.test/v1", model: str = "glm-5.3-flash") -> ModelCapabilityKey:
    return ModelCapabilityKey(base_url=base_url, model=model)


@pytest.mark.asyncio
async def test_unknown_model_is_not_unsupported(monkeypatch):
    async def no_catalog(*args, **kwargs):
        return None

    resolver = ModelCapabilityResolver(catalog_lookup=no_catalog)
    monkeypatch.setattr(resolver, "_discover", no_catalog)

    decision = await resolver.resolve_vision(_key())

    assert decision.state is VisionCapability.UNKNOWN
    assert decision.source == "unknown"


@pytest.mark.asyncio
async def test_litellm_positive_hint_marks_supported():
    async def no_discovery(*args, **kwargs):
        return None

    resolver = ModelCapabilityResolver(
        catalog_lookup=lambda model: {"supports_vision": True},
        discovery=no_discovery,
    )

    decision = await resolver.resolve_vision(_key())

    assert decision.state is VisionCapability.SUPPORTED
    assert decision.source == "catalog"


@pytest.mark.asyncio
async def test_litellm_false_or_missing_stays_unknown():
    async def no_discovery(*args, **kwargs):
        return None

    for info in ({"supports_vision": False}, {}, None):
        resolver = ModelCapabilityResolver(catalog_lookup=lambda model, info=info: info, discovery=no_discovery)
        decision = await resolver.resolve_vision(_key(model=f"custom-{id(info)}"))
        assert decision.state is VisionCapability.UNKNOWN


@pytest.mark.asyncio
async def test_openrouter_metadata_supports_and_rejects_image():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        model = "vision-model" if "vision-model" in str(request.url) else "text-model"
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": model,
                    "architecture": {"input_modalities": ["text", "image"] if model == "vision-model" else ["text"]},
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        resolver = ModelCapabilityResolver(http_client=client, catalog_lookup=lambda model: None)
        supported = await resolver.resolve_vision(
            ModelCapabilityKey("https://openrouter.ai/api/v1", "openrouter/vision-model")
        )
        unsupported = await resolver.resolve_vision(
            ModelCapabilityKey("https://openrouter.ai/api/v1", "openrouter/text-model")
        )
    finally:
        await client.aclose()

    assert supported.state is VisionCapability.SUPPORTED
    assert unsupported.state is VisionCapability.UNSUPPORTED
    assert any("openrouter.ai" in url for url in seen)


@pytest.mark.asyncio
async def test_ollama_and_lm_studio_metadata_adapters():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 11434:
            assert request.url.path == "/api/show"
            return httpx.Response(200, json={"capabilities": ["completion", "vision"]})
        assert request.url.port == 1234
        assert request.url.path == "/api/v0/models"
        return httpx.Response(200, json={"data": [{"id": "local-vlm", "type": "vlm"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        resolver = ModelCapabilityResolver(http_client=client, catalog_lookup=lambda model: None)
        ollama = await resolver.resolve_vision(ModelCapabilityKey("http://127.0.0.1:11434/v1", "gemma3"))
        lmstudio = await resolver.resolve_vision(ModelCapabilityKey("http://127.0.0.1:1234/v1", "local-vlm"))
    finally:
        await client.aclose()

    assert ollama.state is VisionCapability.SUPPORTED
    assert lmstudio.state is VisionCapability.SUPPORTED


@pytest.mark.asyncio
async def test_metadata_failure_and_unknown_model_stay_unknown():
    async def discovery(*args, **kwargs):
        return None

    resolver = ModelCapabilityResolver(discovery=discovery, catalog_lookup=lambda model: None)
    first = await resolver.resolve_vision(_key())
    second = await resolver.resolve_vision(_key())

    assert first.state is VisionCapability.UNKNOWN
    assert second.state is VisionCapability.UNKNOWN


@pytest.mark.asyncio
async def test_discovery_or_catalog_exception_stays_unknown():
    async def discovery(*args, **kwargs):
        raise TimeoutError("metadata timeout")

    def catalog(_model):
        raise RuntimeError("catalog unavailable")

    resolver = ModelCapabilityResolver(discovery=discovery, catalog_lookup=catalog)
    decision = await resolver.resolve_vision(_key())
    assert decision.state is VisionCapability.UNKNOWN


def test_capability_cache_is_scoped_and_has_ttl(monkeypatch):
    resolver = ModelCapabilityResolver(clock=lambda: 100.0)
    first = _key()
    other_model = _key(model="other")
    other_base = _key(base_url="https://other.example.test/v1")

    resolver.record_success(first)
    assert resolver.cached(first).state is VisionCapability.SUPPORTED
    assert resolver.cached(other_model) is None
    assert resolver.cached(other_base) is None

    resolver._clock = lambda: 100.0 + 86_400
    assert resolver.cached(first) is None

    resolver._clock = lambda: 200.0
    resolver.record_unsupported(first)
    assert resolver.cached(first).state is VisionCapability.UNSUPPORTED
    resolver._clock = lambda: 200.0 + 3_600
    assert resolver.cached(first) is None


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("400 vision_not_supported: image input is unsupported"),
        RuntimeError("415 图片格式不支持，vision input rejected"),
        RuntimeError("422 image_url does not support this content type"),
    ],
)
def test_explicit_vision_rejection_is_classified(exc):
    exc.status_code = int(str(exc).split(" ", 1)[0])
    assert is_explicit_vision_rejection(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("401 image token expired"),
        RuntimeError("429 vision rate limit"),
        RuntimeError("500 image backend unavailable"),
        RuntimeError("400 context length exceeded"),
        RuntimeError("400 bad request"),
        TimeoutError(),
    ],
)
def test_transient_or_ambiguous_errors_are_not_vision_rejections(exc):
    if isinstance(exc, RuntimeError):
        exc.status_code = int(str(exc).split(" ", 1)[0])
    assert is_explicit_vision_rejection(exc) is False
