"""只针对 ~/.LiBao/settings.json 的一次性兼容升级。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings


def normalize_legacy_model_prefix(settings: Any = None) -> bool:
    """去掉旧配置中遗留的 provider/ 模型名前缀，并写回用户配置。"""
    settings = settings or get_settings()
    model = getattr(settings, "llm_model", "") or ""
    if "/" not in model:
        return False
    bare = model.split("/", 1)[1]
    settings.llm_model = bare
    settings_file = Path(getattr(settings, "agent_data_dir", "")) / "settings.json"
    if settings_file.is_file():
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        if isinstance(data, dict) and data.get("llm_model") == model:
            data["llm_model"] = bare
            settings_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def initialize_user_settings(settings: Any = None) -> bool:
    """首次启动时在 ~/.LiBao 写入当前支持字段的默认配置。"""
    settings = settings or get_settings()
    user_root = Path(getattr(settings, "agent_data_dir", ""))
    settings_file = user_root / "settings.json"
    if settings_file.exists():
        return False
    user_root.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True
