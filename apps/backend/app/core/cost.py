"""成本估算（《02》接口契约 §5.8 /system/cost，《04》路线图 M5）。

token×定价表估算（USD/百万 token），非 provider 账单；LiteLLM 响应含真实 cost 时
优先使用（M4 接缝）。model 前缀命中 provider 单价，未知 provider 走兜底。
"""

from __future__ import annotations

from typing import Any

# 每百万 token 单价（USD）：provider 前缀 → (input, output)
_RATES: dict[str, tuple[float, float]] = {
    "deepseek": (0.14, 0.28),
    "siliconflow": (0.15, 0.30),
    "qwen": (0.15, 0.30),
    "openai": (2.50, 10.00),
    "anthropic": (3.00, 15.00),
}
_FALLBACK = (1.00, 2.00)


# 纯 OpenAI 裸名（2026-08-27）：不带厂商前缀，需显式映射到 provider（deepseek-/qwen- 等已由 _RATES 前缀命中）
_OPENAI_BARE_PREFIXES = ("gpt-", "o1-", "o3-", "o4-", "chatgpt-")
_ANTHROPIC_BARE_PREFIXES = ("claude-")


def provider_for(model: str) -> str:
    """model → provider（未知兜底 "unknown"）。兼容裸名（gpt-4o→openai）与旧前缀名。"""
    model = (model or "").lower()
    if model.startswith(_OPENAI_BARE_PREFIXES):
        return "openai"
    if model.startswith(_ANTHROPIC_BARE_PREFIXES):
        return "anthropic"
    return next((p for p in _RATES if model.startswith(p)), "unknown")


def estimate_cost(usage: dict[str, Any] | None, model: str) -> float:
    """按 usage_metadata（input/output tokens）估算成本（USD，6 位小数）。"""
    if not usage:
        return 0.0
    provider = provider_for(model)
    rate_in, rate_out = _RATES.get(provider, _FALLBACK)
    in_tokens = int(usage.get("input_tokens", 0) or 0)
    out_tokens = int(usage.get("output_tokens", 0) or 0)
    return round(in_tokens / 1e6 * rate_in + out_tokens / 1e6 * rate_out, 6)
