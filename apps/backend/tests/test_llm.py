"""LLM 封装测试（纯 OpenAI 协议，2026-08-27）：URL 归一化 + build_model 参数。"""
from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.core.llm import resolve_openai_base_url


def test_resolve_base_url_none():
    assert resolve_openai_base_url(None, False) is None
    assert resolve_openai_base_url("", False) is None


def test_resolve_base_url_base_mode_strips_trailing_slash():
    assert resolve_openai_base_url("https://api.deepseek.com", False) == "https://api.deepseek.com"
    assert resolve_openai_base_url("https://api.openai.com/v1/", False) == "https://api.openai.com/v1"


def test_resolve_base_url_full_url_strips_chat_completions():
    assert (
        resolve_openai_base_url("https://api.deepseek.com/v1/chat/completions", True)
        == "https://api.deepseek.com/v1"
    )


def test_resolve_base_url_full_url_without_suffix():
    assert resolve_openai_base_url("https://api.deepseek.com/v1", True) == "https://api.deepseek.com/v1"


def test_build_model_uses_chatopenai_kwargs(monkeypatch):
    from app.core import llm as llm_mod

    captured: dict[str, object] = {}

    class _FakeChat:
        def __init__(self, **kw: object) -> None:
            captured.update(kw)

    monkeypatch.setattr(llm_mod, "ReasoningChatOpenAI", _FakeChat)
    s = SimpleNamespace(llm_model="deepseek-chat", llm_api_key="sk-x", llm_base_url="https://api.deepseek.com")
    llm_mod.LLMService.build_model(settings=s)
    assert captured["model"] == "deepseek-chat"
    assert captured["api_key"] == "sk-x"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["streaming"] is True
    assert captured["max_retries"] == 0
    assert captured["stream_chunk_timeout"] == 300.0
    assert "max_tokens" not in captured
    assert "context_window" not in captured


def test_classify_llm_transport_failures():
    from app.core.errors import LLMFailureKind, classify_llm_exception

    cases = [
        httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
        httpx.ReadTimeout("read timed out"),
        RuntimeError("No streaming chunk received for 120.0s"),
        RuntimeError("incomplete chunked read"),
    ]
    assert all(classify_llm_exception(exc) is LLMFailureKind.TRANSPORT for exc in cases)


def test_context_and_auth_errors_are_not_transport_recoverable():
    from app.core.errors import LLMFailureKind, classify_llm_exception

    cases = [
        RuntimeError("maximum context length is 256000 tokens"),
        RuntimeError("HTTP 400 invalid request"),
        RuntimeError("HTTP 401 unauthorized"),
        RuntimeError("HTTP 429 rate limit exceeded"),
    ]
    assert all(classify_llm_exception(exc) is not LLMFailureKind.TRANSPORT for exc in cases)


def test_normalized_transport_error_redacts_payload():
    from app.core.errors import LLMTransportError, normalize_llm_exception

    exc = RuntimeError(
        "peer closed https://gateway.invalid/chat?api_key=secret-key; "
        "response body secret-body and prompt nonce-prompt"
    )
    normalized = normalize_llm_exception(
        exc,
        model="glm-5.3-flash",
        context_metrics={"estimated_prompt_tokens": 12},
    )
    assert isinstance(normalized, LLMTransportError)
    assert normalized.code == 60008
    assert normalized.retryable is True
    assert normalized.recoverable is True
    details = str(normalized.details)
    assert "secret-key" not in details
    assert "secret-body" not in details
    assert "nonce-prompt" not in details
    assert normalized.details["model"] == "glm-5.3-flash"


def test_build_model_falls_back_to_settings_model(monkeypatch):
    from app.core import llm as llm_mod

    captured: dict[str, object] = {}

    class _FakeChat:
        def __init__(self, **kw: object) -> None:
            captured.update(kw)

    monkeypatch.setattr(llm_mod, "ReasoningChatOpenAI", _FakeChat)
    s = SimpleNamespace(llm_model="gpt-4o", llm_api_key="", llm_base_url="")
    llm_mod.LLMService.build_model(settings=s)  # model=None → 回落 settings.llm_model
    assert captured["model"] == "gpt-4o"
    assert "api_key" not in captured  # 空 key 不传
    assert "base_url" not in captured  # 空 base 不传


def test_reasoning_delta_extraction():
    """DeepSeek 推理模型 reasoning_content 从流式 delta 提取（langchain-openai base 会丢弃）。"""
    from app.core.llm import ReasoningChatOpenAI

    chunk = {"choices": [{"delta": {"reasoning_content": "思考", "content": ""}}]}
    assert ReasoningChatOpenAI._delta_reasoning(chunk) == "思考"
    assert ReasoningChatOpenAI._delta_reasoning({"choices": [{"delta": {"content": "hi"}}]}) is None
    assert ReasoningChatOpenAI._delta_reasoning({"choices": []}) is None


def test_reasoning_chunk_conversion_extracts_reasoning():
    """流式 chunk 转换把 reasoning_content 放进 additional_kwargs（stream_core 据此发 thinking 事件）。"""
    from langchain_core.messages import AIMessageChunk

    from app.core.llm import ReasoningChatOpenAI

    m = ReasoningChatOpenAI(model="deepseek-v4-flash", api_key="sk-x")
    chunk = {
        "choices": [{"delta": {"role": "assistant", "reasoning_content": "思考", "content": ""}, "finish_reason": None}]
    }
    gen = m._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert gen is not None
    assert gen.message.additional_kwargs["reasoning_content"] == "思考"
