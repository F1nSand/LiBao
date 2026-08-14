"""LLM 统一封装（docs 01 §6 core/llm.py）。

LiteLLM 一家接多家：DeepSeek（默认，国内直连）/ Ollama（本地）/ OpenAI 等。
build_model(model) 返回 streaming 的 ChatLiteLLM；api_key / api_base 从 Settings 注入（凭证只走 env，不入库）。
"""
from __future__ import annotations

from typing import Any

from langchain_litellm import ChatLiteLLM

from app.core.config import Settings, get_settings


def _patch_reasoning_content_passthrough() -> None:
    """langchain-litellm 0.7.0 上游 bug 补丁。

    `_convert_message_to_dict` 丢弃 thinking 块且不输出 reasoning_content →
    DeepSeek 推理模型（如 deepseek-v4-flash）多轮/工具调用报 400
    "reasoning_content must be passed back"。补丁：AIMessage 的
    additional_kwargs["reasoning_content"]（响应解析时已存）在转换时透传。
    """
    import langchain_litellm.chat_models.litellm as _ll

    if getattr(_ll, "_REASONING_PATCHED", False):
        return
    _orig = _ll._convert_message_to_dict

    def _patched(message: Any) -> dict[str, Any]:
        d = _orig(message)
        if d.get("role") != "assistant":
            return d
        rc = getattr(message, "additional_kwargs", {}).get("reasoning_content")
        if rc:
            d["reasoning_content"] = rc
        # 推理模型 content 是块列表（thinking + 文本字符串混排）→ 规范化为纯文本字符串，
        # 否则 DeepSeek 收到字符串数组 content 直接 400（litellm 映射该错误还有 bug）
        if isinstance(d.get("content"), list):
            text = "".join(
                (item.get("text", "") if isinstance(item, dict) else str(item))
                for item in d["content"]
                if not (isinstance(item, dict) and item.get("type") in ("thinking", "redacted_thinking"))
            )
            d["content"] = text
        return d

    _ll._convert_message_to_dict = _patched
    _ll._REASONING_PATCHED = True


_patch_reasoning_content_passthrough()


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
