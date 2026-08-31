"""LLM 统一封装（《02》后端设计 §6 core/llm.py）。

纯 OpenAI 协议（2026-08-27）：统一走 langchain-openai 的 ChatOpenAI，模型名裸写（gpt-4o/deepseek-chat），
base_url 走 OpenAI 兼容端点（provider 同步时已归一化为 base）。api_key / base_url 从 Settings 注入。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from app.core.config import Settings, get_settings

_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"


def resolve_openai_base_url(base_url: str | None, is_full_url: bool) -> str | None:
    """请求地址归一化为 OpenAI base（供 ChatOpenAI(base_url=...) 自动拼 /chat/completions）。

    - base_url 为空 → None
    - is_full_url=True：用户填完整 URL（含 /chat/completions），剥掉后缀作为 base
    - is_full_url=False：用户填 base，去尾斜杠直接作为 base
    """
    if not base_url:
        return None
    if is_full_url and base_url.endswith(_CHAT_COMPLETIONS_SUFFIX):
        return base_url[: -len(_CHAT_COMPLETIONS_SUFFIX)]
    return base_url.rstrip("/")


class ReasoningChatOpenAI(ChatOpenAI):
    """DeepSeek 推理模型兼容（langchain-openai base 故意不提取 reasoning_content，见其源码注释）。

    补两处，否则 DeepSeek 推理模型（deepseek-v4-flash）的思考轨迹丢失 + 多轮 400：
    1. 响应解析（流式 chunk）把 delta.reasoning_content 提取到 additional_kwargs["reasoning_content"]
       （stream_core 据此发 thinking 事件）。
    2. 请求序列化透传 additional_kwargs["reasoning_content"] 回 DeepSeek（推理模型多轮
       "reasoning_content must be passed back"）。
    """

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None
    ) -> Any:
        gen = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if gen is not None and gen.message is not None:
            rc = self._delta_reasoning(chunk)
            if rc:
                gen.message.additional_kwargs["reasoning_content"] = rc
        return gen

    @staticmethod
    def _delta_reasoning(chunk: dict) -> str | None:
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        if not choices:
            return None
        delta = (choices[0].get("delta") or {})
        return delta.get("reasoning_content") or None

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        msgs = payload.get("messages")
        if msgs:
            try:
                input_msgs = self._convert_input(input_).to_messages()
            except Exception:  # noqa: BLE001  透传 best-effort，失败不阻断
                return payload
            # 逐消息对齐（_get_request_payload 内部也是逐消息 _convert_message_to_dict，数量/顺序不变）
            for d, m in zip(msgs, input_msgs, strict=False):
                if d.get("role") == "assistant" and isinstance(m, AIMessage):
                    rc = m.additional_kwargs.get("reasoning_content")
                    if rc:
                        d["reasoning_content"] = rc
        return payload

    def _create_chat_result(self, response: Any, generation_info: dict | None = None) -> Any:
        """非流式响应也提取 reasoning_content（build_model 恒 streaming=True，此处为完整性兜底）。"""
        result = super()._create_chat_result(response, generation_info)
        rc: str | None = None
        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                rc = (choices[0].get("message") or {}).get("reasoning_content")
        elif getattr(response, "choices", None):
            rc = getattr(response.choices[0].message, "reasoning_content", None)
        if rc and result.generations:
            result.generations[0].message.additional_kwargs["reasoning_content"] = rc
        return result


class LLMService:
    @staticmethod
    def build_model(model: str | None = None, settings: Settings | None = None) -> ChatOpenAI:
        settings = settings or get_settings()
        kwargs: dict[str, Any] = {
            "model": model or settings.llm_model,
            "streaming": True,
            # 重试必须由 graph 的 checkpoint-aware orchestration 控制，避免 SDK
            # 在半截响应后自行重放请求，造成工具/消息边界不可观测。
            "max_retries": 0,
            "stream_chunk_timeout": getattr(settings, "llm_stream_chunk_timeout_s", 300.0),
        }
        if settings.llm_api_key:
            kwargs["api_key"] = settings.llm_api_key
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url  # 已是 base（sync 归一化后）
        return ReasoningChatOpenAI(**kwargs)
