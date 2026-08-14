"""LLM 统一封装（docs 01 §6 core/llm.py）。

LiteLLM 一家接多家：DeepSeek（默认，国内直连）/ Ollama（本地）/ OpenAI 等。
build_model(model) 返回 streaming 的 ChatLiteLLM；api_key / api_base 从 Settings 注入（凭证只走 env，不入库）。
"""
from __future__ import annotations

from typing import Any

from langchain_litellm import ChatLiteLLM

from app.core.config import Settings, get_settings


class ReasoningChatLiteLLM(ChatLiteLLM):
    """DeepSeek 推理模型兼容（langchain-litellm 0.7.0 上游 bug，类级补丁而非全局 monkeypatch）。

    上游 `_convert_message_to_dict` 丢弃 thinking 块且不输出 reasoning_content →
    DeepSeek 推理模型（deepseek-v4-flash）多轮/工具调用报 400
    "reasoning_content must be passed back"。子类在转换后补：
    additional_kwargs["reasoning_content"]（响应解析时已存）透传 + content 规范化为纯文本字符串
    （字符串数组 content 也会被 DeepSeek 400）。
    """

    def _create_message_dicts(
        self, messages: list[Any], stop: list[str] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        message_dicts, params = super()._create_message_dicts(messages, stop)
        for d, m in zip(message_dicts, messages, strict=True):
            if d.get("role") != "assistant":
                continue
            rc = getattr(m, "additional_kwargs", {}).get("reasoning_content")
            if rc:
                d["reasoning_content"] = rc
            if isinstance(d.get("content"), list):
                d["content"] = "".join(
                    (item.get("text", "") if isinstance(item, dict) else str(item))
                    for item in d["content"]
                    if not (isinstance(item, dict) and item.get("type") in ("thinking", "redacted_thinking"))
                )
        return message_dicts, params


class LLMService:
    @staticmethod
    def build_model(model: str | None = None, settings: Settings | None = None) -> ChatLiteLLM:
        settings = settings or get_settings()
        kwargs: dict[str, Any] = {"model": model or settings.llm_model, "streaming": True}
        if settings.llm_api_key:
            kwargs["api_key"] = settings.llm_api_key
        if settings.llm_base_url:
            kwargs["api_base"] = settings.llm_base_url
        return ReasoningChatLiteLLM(**kwargs)
