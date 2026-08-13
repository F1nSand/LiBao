"""LLM 统一封装（docs 01 §6 core/llm.py）。

LiteLLM 一家接多家：DeepSeek（默认，国内直连）/ Ollama（本地）/ OpenAI 等。
build_model(model) 返回 streaming 的 ChatLiteLLM；api_key / api_base 从 Settings 注入（凭证只走 env，不入库）。
"""
from __future__ import annotations

from typing import Any

from langchain_litellm import ChatLiteLLM

from app.core.config import Settings, get_settings


class LLMService:
    @staticmethod
    def build_model(model: str | None = None, settings: Settings | None = None) -> ChatLiteLLM:
        settings = settings or get_settings()
        kwargs: dict[str, Any] = {"model": model or settings.llm_model, "streaming": True}
        if settings.llm_api_key:
            kwargs["api_key"] = settings.llm_api_key
        if settings.llm_base_url:
            kwargs["api_base"] = settings.llm_base_url
        return ChatLiteLLM(**kwargs)
