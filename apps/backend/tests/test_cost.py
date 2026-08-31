"""2b 成本估算测试（纯单元，token×定价表）。"""
from __future__ import annotations

from app.core.cost import estimate_cost, provider_for


def test_estimate_cost_deepseek():
    cost = estimate_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000}, "deepseek/deepseek-v4-flash")
    assert cost == round(0.14 + 0.28, 6)


def test_estimate_cost_zero_usage():
    assert estimate_cost({}, "any") == 0.0
    assert estimate_cost(None, "any") == 0.0


def test_estimate_cost_fallback_unknown():
    cost = estimate_cost({"input_tokens": 1_000_000, "output_tokens": 0}, "weird-model")
    assert cost == 1.00  # fallback input 单价


def test_provider_for():
    assert provider_for("deepseek/deepseek-v4-flash") == "deepseek"  # 旧 liteLLM 前缀名
    assert provider_for("openai/gpt-4o") == "openai"
    assert provider_for("") == "unknown"


def test_provider_for_bare_names():
    """纯 OpenAI 裸名（2026-08-27）：无厂商前缀，按裸名特征映射。"""
    assert provider_for("gpt-4o") == "openai"
    assert provider_for("o1-mini") == "openai"
    assert provider_for("deepseek-chat") == "deepseek"
    assert provider_for("qwen-max") == "qwen"
    assert provider_for("claude-3.5-sonnet") == "anthropic"
    assert provider_for("some-custom-model") == "unknown"
