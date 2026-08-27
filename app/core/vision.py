"""视觉能力判定（2026-08-27 多模态适配，docs 01 §6）。

两层：provider 显式声明（capabilities=["vision"] → Settings.llm_vision_declared）优先；
未声明回落内置 pattern 表（default-deny，只收高置信多模态名——把图发给纯文本模型的
API 400 比漏判降级的破坏大）。
"""

from __future__ import annotations

# 高置信视觉模型名 pattern（子串匹配，小写）。宁可漏判（降级提示）不可错判（400）。
VISION_MODEL_PATTERNS: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "o3",
    "o4-mini",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "qvq",
    "glm-4v",
    "gemini",
    "claude-3",
    "claude-4",
    "hunyuan-vision",
    "yi-vision",
    "pixtral",
    "internvl",
    "llava",
)


def has_vision_pattern(model: str) -> bool:
    """effective model 名（小写化）命中任一视觉 pattern。"""
    m = (model or "").lower()
    return any(p in m for p in VISION_MODEL_PATTERNS)


def supports_vision(model: str, declared: bool | None) -> bool:
    """最终判定：declared 非 None 直接采信（True/False 均可压制 pattern）；None 回落 pattern。

    declared 来源 ProviderConfig.capabilities：["vision"]→True；其他非空列表→False；空→None。
    """
    if declared is not None:
        return declared
    return has_vision_pattern(model)
