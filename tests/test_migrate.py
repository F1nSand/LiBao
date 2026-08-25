"""migrate_to_libao 迁移测试（2026-08-25）：旧项目根数据 → ~/.LiBao（幂等、root_path 重写、settings.json）。

也验证 config.py 优先读 ~/.LiBao/settings.json（JSON），.env 后备。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import app.core.config as cfg
from app.core import migrate


def _make_legacy(root: Path) -> None:
    """构造旧布局（项目根 .agent/data/kb/uploads + .env）。"""
    (root / ".agent" / "sessions").mkdir(parents=True)
    (root / ".agent" / "sessions" / "c1.jsonl").write_text("{}", encoding="utf-8")
    (root / ".agent" / "workspaces.json").write_text(
        json.dumps({"version": 1, "items": {"ws1": {"id": "ws1", "root_path": "data/workspaces/ws1"}}}),
        encoding="utf-8",
    )
    (root / "data" / "workspaces" / "ws1").mkdir(parents=True)
    (root / "data" / "workspaces" / "ws1" / "f.txt").write_text("x", encoding="utf-8")
    (root / "kb").mkdir(parents=True)
    (root / "kb" / "vectors.lance").write_text("lance", encoding="utf-8")
    (root / "uploads").mkdir(parents=True)
    (root / "uploads" / "u1.bin").write_text("bin", encoding="utf-8")
    (root / ".env").write_text("LLM_API_KEY=sk-test\nUPLOAD_DIR=uploads\nGITHUB_TOKEN=tok\n", encoding="utf-8")


def test_migrate_to_libao(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    _make_legacy(legacy)
    lib = tmp_path / "libao"
    monkeypatch.setattr(migrate, "_project_root", lambda: legacy)
    monkeypatch.setattr(migrate, "get_settings", lambda: SimpleNamespace(agent_data_dir=str(lib)))

    assert migrate.migrate_to_libao() is True
    # ① 数据复制（.agent/data/kb/uploads → lib）
    assert (lib / "sessions" / "c1.jsonl").is_file()
    assert (lib / "workspaces" / "ws1" / "f.txt").is_file()
    assert (lib / "kb" / "vectors.lance").is_file()
    assert (lib / "uploads" / "u1.bin").is_file()
    # ② workspaces root_path 重写（旧 data/workspaces/ws1 → ~/.LiBao/workspaces/ws1）
    ws = json.loads((lib / "workspaces.json").read_text(encoding="utf-8"))
    assert ws["items"]["ws1"]["root_path"] == str((lib / "workspaces" / "ws1").resolve())
    # ③ settings.json：非路径 key 迁移 + 路径字段绝对化（覆盖 .env 相对 UPLOAD_DIR）
    st = json.loads((lib / "settings.json").read_text(encoding="utf-8"))
    assert st["llm_api_key"] == "sk-test"
    assert st["github_token"] == "tok"
    assert st["upload_dir"] == str(lib / "uploads")
    assert st["agent_data_dir"] == str(lib)
    # ④ 幂等（标记存在 → 第二次跳过）
    assert migrate.migrate_to_libao() is False


def test_migrate_skips_when_no_legacy(monkeypatch, tmp_path):
    """无旧数据（空项目根）→ 不迁移。注意用 tmp_path 子目录避开 autouse _filestore 创建的 .agent 骨架。"""
    lib = tmp_path / "libao"
    empty_root = tmp_path / "empty_root"
    empty_root.mkdir()  # 真正空目录（无 .agent/data/kb/uploads）
    monkeypatch.setattr(migrate, "_project_root", lambda: empty_root)
    monkeypatch.setattr(migrate, "get_settings", lambda: SimpleNamespace(agent_data_dir=str(lib)))
    assert migrate.migrate_to_libao() is False
    assert not (lib / "sessions").exists()


def test_settings_reads_from_settings_json(monkeypatch, tmp_path):
    """~/.LiBao/settings.json 优先于 .env/默认（settings_customise_sources）。"""
    lib = tmp_path / "libao"
    lib.mkdir()
    (lib / "settings.json").write_text(
        json.dumps({"llm_api_key": "json-key", "upload_dir": str(lib / "uploads")}), encoding="utf-8"
    )
    original_lib = cfg._LIB
    monkeypatch.setattr(cfg, "_LIB", str(lib))
    cfg.get_settings.cache_clear()
    try:
        s = cfg.get_settings()
        assert s.llm_api_key == "json-key"
        assert s.upload_dir == str(lib / "uploads")
    finally:
        cfg.get_settings.cache_clear()
        monkeypatch.setattr(cfg, "_LIB", original_lib)


def test_settings_json_absent_uses_default(monkeypatch, tmp_path):
    """无 settings.json → 不报错，配置从 .env/默认读取（agent_data_dir 走 ~/.LiBao 布局）。"""
    lib = tmp_path / "empty_lib"
    lib.mkdir()  # 无 settings.json
    original_lib = cfg._LIB
    monkeypatch.setattr(cfg, "_LIB", str(lib))
    cfg.get_settings.cache_clear()
    try:
        s = cfg.get_settings()
        assert s.llm_model  # 非空（.env 或默认）
        assert s.agent_data_dir.endswith(".LiBao")  # 默认 ~/.LiBao 布局
    finally:
        cfg.get_settings.cache_clear()
        monkeypatch.setattr(cfg, "_LIB", original_lib)
