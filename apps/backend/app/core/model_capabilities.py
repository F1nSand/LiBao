"""运行期模型能力发现（不依赖 Provider 配置或模型名称名单）。

能力判断只回答“这个具体 endpoint/model/transport 组合是否接受图片输入”。
UNKNOWN 不是 UNSUPPORTED：未知时由调用边界执行一次真实携图请求，再根据结果学习。
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx


class VisionCapability(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ModelCapabilityKey:
    """不包含密钥的能力缓存键。"""

    base_url: str
    model: str
    transport: str = "openai-chat-completions"

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _normalize_base_url(self.base_url))
        object.__setattr__(self, "model", (self.model or "").strip().lower())
        object.__setattr__(self, "transport", (self.transport or "openai-chat-completions").strip().lower())


@dataclass(frozen=True, slots=True)
class VisionDecision:
    state: VisionCapability
    source: str
    key: ModelCapabilityKey


CatalogLookup = Callable[[str], Any]
DiscoveryLookup = Callable[
    [ModelCapabilityKey, str | None], Awaitable[VisionCapability | None] | VisionCapability | None
]


def _normalize_base_url(value: str | None) -> str:
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.hostname:
        return raw.lower()
    host = parsed.hostname.lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip("/"), "", ""))


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if value is None:
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _exception_text(exc: Exception) -> str:
    parts = [str(exc)]
    for attr in ("body", "code", "message"):
        value = getattr(exc, attr, None)
        if value is not None:
            parts.append(str(value))
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            parts.append(response.text)
        except Exception:  # noqa: BLE001 - 只用于错误分类，不能覆盖原始异常
            pass
    return " ".join(parts).lower()


def is_explicit_vision_rejection(exc: Exception) -> bool:
    """仅识别明确的图片/视觉能力拒绝，不把通用请求失败写成负能力缓存。"""

    if _status_code(exc) not in {400, 415, 422}:
        return False
    text = _exception_text(exc)
    structured = (
        "unsupported_media_type" in text
        or "unsupported_content_type" in text
        or "image_not_supported" in text
        or "vision_not_supported" in text
        or "invalid_image_url" in text
    )
    if structured:
        return True
    modality = (
        "image" in text
        or "image_url" in text
        or "vision" in text
        or "multimodal" in text
        or "图片" in text
        or "视觉" in text
    )
    rejection = (
        "unsupported" in text
        or "not support" in text
        or "does not support" in text
        or "不支持" in text
        or "无法处理" in text
        or "rejected" in text
    )
    return modality and rejection


def _capability_from_modalities(values: Any) -> VisionCapability | None:
    if not isinstance(values, list):
        return None
    normalized = {str(value).strip().lower() for value in values}
    if "image" in normalized:
        return VisionCapability.SUPPORTED
    if normalized:
        return VisionCapability.UNSUPPORTED
    return None


def _model_id_matches(requested: str, returned: str) -> bool:
    requested = requested.lower()
    returned = returned.lower()
    return requested == returned or requested.rsplit("/", 1)[-1] == returned


class ModelCapabilityResolver:
    """同源元数据 + 正向目录 + 运行期结果的进程内 TTL 缓存。"""

    POSITIVE_TTL = 86_400.0
    NEGATIVE_TTL = 3_600.0
    UNKNOWN_TTL = 300.0
    DISCOVERY_TIMEOUT = 1.5

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        catalog_lookup: CatalogLookup | None = None,
        discovery: DiscoveryLookup | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._http_client = http_client
        self._catalog_lookup = catalog_lookup or self._litellm_lookup
        self._discovery_override = discovery
        self._clock = clock or time.monotonic
        self._cache: dict[ModelCapabilityKey, tuple[VisionCapability, str, float]] = {}

    @staticmethod
    def _litellm_lookup(model: str) -> dict[str, Any] | None:
        try:
            import litellm

            info = litellm.get_model_info(model)
        except Exception:  # noqa: BLE001 - 目录缺失不能阻断真实请求
            return None
        return info if isinstance(info, dict) else None

    def cached(self, key: ModelCapabilityKey) -> VisionDecision | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        state, source, expires_at = entry
        if self._clock() >= expires_at:
            self._cache.pop(key, None)
            return None
        return VisionDecision(state=state, source=source, key=key)

    def _remember(self, key: ModelCapabilityKey, state: VisionCapability, source: str) -> VisionDecision:
        ttl = {
            VisionCapability.SUPPORTED: self.POSITIVE_TTL,
            VisionCapability.UNSUPPORTED: self.NEGATIVE_TTL,
            VisionCapability.UNKNOWN: self.UNKNOWN_TTL,
        }[state]
        self._cache[key] = (state, source, self._clock() + ttl)
        return VisionDecision(state=state, source=source, key=key)

    async def resolve_vision(self, key: ModelCapabilityKey, api_key: str | None = None) -> VisionDecision:
        cached = self.cached(key)
        if cached is not None:
            return cached

        try:
            discovered = await self._discover(key, api_key)
        except Exception:  # noqa: BLE001 - discovery is advisory; a timeout must remain UNKNOWN
            discovered = None
        if discovered is not None:
            return self._remember(key, discovered, "metadata")

        try:
            info = self._catalog_lookup(key.model)
            if inspect.isawaitable(info):
                info = await info
        except Exception:  # noqa: BLE001 - an unavailable catalog cannot veto a real request
            info = None
        if isinstance(info, dict) and info.get("supports_vision") is True:
            return self._remember(key, VisionCapability.SUPPORTED, "catalog")
        return self._remember(key, VisionCapability.UNKNOWN, "unknown")

    async def _discover(self, key: ModelCapabilityKey, api_key: str | None = None) -> VisionCapability | None:
        if self._discovery_override is not None:
            result = self._discovery_override(key, api_key)
            if inspect.isawaitable(result):
                result = await result
            return result

        parsed = urlsplit(key.base_url)
        host = (parsed.hostname or "").lower()
        try:
            if host == "openrouter.ai":
                payload = await self._request_json(
                    f"https://openrouter.ai/api/v1/model/{quote(key.model, safe='/')}", api_key=api_key
                )
                data = payload.get("data") if isinstance(payload, dict) else None
                return _capability_from_modalities((data or {}).get("architecture", {}).get("input_modalities"))
            if parsed.port == 11434:
                payload = await self._request_json(
                    f"{parsed.scheme}://{parsed.netloc}/api/show",
                    method="POST",
                    json={"model": key.model},
                    api_key=api_key,
                )
                caps = payload.get("capabilities") if isinstance(payload, dict) else None
                return _capability_from_modalities(["image"] if isinstance(caps, list) and "vision" in caps else caps)
            if parsed.port == 1234:
                payload = await self._request_json(f"{parsed.scheme}://{parsed.netloc}/api/v0/models", api_key=api_key)
                models = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(models, list):
                    return None
                for item in models:
                    if isinstance(item, dict) and _model_id_matches(key.model, str(item.get("id", ""))):
                        return VisionCapability.SUPPORTED if item.get("type") == "vlm" else VisionCapability.UNSUPPORTED
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        return None

    async def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        json: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        if self._http_client is not None:
            response = await self._http_client.request(method, url, json=json, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self.DISCOVERY_TIMEOUT) as client:
                response = await client.request(method, url, json=json, headers=headers)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def record_success(self, key: ModelCapabilityKey) -> None:
        self._remember(key, VisionCapability.SUPPORTED, "runtime_success")

    def record_unsupported(self, key: ModelCapabilityKey) -> None:
        self._remember(key, VisionCapability.UNSUPPORTED, "runtime_rejection")

    def clear(self) -> None:
        self._cache.clear()


_resolver = ModelCapabilityResolver()


def get_model_capability_resolver() -> ModelCapabilityResolver:
    return _resolver
