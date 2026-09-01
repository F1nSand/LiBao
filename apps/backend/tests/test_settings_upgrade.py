"""用户配置来源与兼容升级测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import app.core.config as cfg
from app.core import settings_upgrade


def test_settings_reads_from_user_settings_json(monkeypatch, tmp_path):
    """~/.LiBao/settings.json 是项目配置的唯一文件来源。"""
    lib = tmp_path / "libao"
    lib.mkdir()
    (lib / "settings.json").write_text(
        json.dumps({"llm_api_key": "json-key", "upload_dir": str(lib / "uploads")}), encoding="utf-8"
    )
    original_lib = cfg._LIB
    monkeypatch.setattr(cfg, "_LIB", str(lib))
    monkeypatch.setenv("LLM_API_KEY", "environment-key")
    cfg.get_settings.cache_clear()
    try:
        s = cfg.get_settings()
        assert s.llm_api_key == "json-key"
        assert s.upload_dir == str(lib / "uploads")
    finally:
        cfg.get_settings.cache_clear()
        monkeypatch.setattr(cfg, "_LIB", original_lib)


def test_project_environment_is_ignored(monkeypatch, tmp_path):
    """没有用户配置时只使用内置默认值，不回读项目 .env 或进程环境。"""
    original_lib = cfg._LIB
    monkeypatch.setattr(cfg, "_LIB", str(tmp_path / "empty_lib"))
    monkeypatch.setenv("LLM_API_KEY", "must-not-be-read")
    cfg.get_settings.cache_clear()
    try:
        s = cfg.get_settings()
        assert s.llm_api_key == ""
        assert s.llm_model == "deepseek-chat"
    finally:
        cfg.get_settings.cache_clear()
        monkeypatch.setattr(cfg, "_LIB", original_lib)


def test_initialize_user_settings_writes_safe_defaults(tmp_path):
    lib = tmp_path / "libao"
    settings = SimpleNamespace(
        agent_data_dir=str(lib),
        model_dump=lambda mode: {"agent_data_dir": str(lib), "llm_api_key": "", "debug": True},
    )
    assert settings_upgrade.initialize_user_settings(settings) is True
    assert json.loads((lib / "settings.json").read_text(encoding="utf-8"))["llm_api_key"] == ""
    assert settings_upgrade.initialize_user_settings(settings) is False


def test_normalize_legacy_model_prefix_strips(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps({"llm_model": "deepseek/deepseek-v4-flash", "llm_api_key": "test-settings-key"}),
        encoding="utf-8",
    )
    settings = SimpleNamespace(llm_model="deepseek/deepseek-v4-flash", agent_data_dir=str(tmp_path))
    assert settings_upgrade.normalize_legacy_model_prefix(settings) is True
    assert settings.llm_model == "deepseek-v4-flash"
    assert json.loads(settings_file.read_text(encoding="utf-8"))["llm_model"] == "deepseek-v4-flash"


def test_normalize_legacy_model_prefix_no_prefix_noop(tmp_path):
    settings = SimpleNamespace(llm_model="deepseek-chat", agent_data_dir=str(tmp_path))
    assert settings_upgrade.normalize_legacy_model_prefix(settings) is False
    assert settings.llm_model == "deepseek-chat"
