from __future__ import annotations

from pathlib import Path

import pytest

from scripts import release_builder


def test_validate_version_accepts_release_names():
    for value in ("0.1.0", "ci-Windows", "smoke_posix.1"):
        assert release_builder.validate_version(value) == value


@pytest.mark.parametrize(
    "value",
    (
        "",
        "..",
        "../escape",
        "..\\escape",
        "/tmp/x",
        "C:\\temp",
        ".hidden",
        "contains space",
        "x" * 65,
    ),
)
def test_validate_version_rejects_path_escape(value: str):
    with pytest.raises(ValueError):
        release_builder.validate_version(value)


def test_release_paths_stay_strictly_under_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(release_builder, "ARTIFACTS", tmp_path / "artifacts")

    stage, archive = release_builder.release_paths("smoke")

    artifacts = (tmp_path / "artifacts").resolve()
    assert stage.resolve().parent == artifacts
    assert archive.resolve().parent == artifacts


def test_release_layout_requires_spa_and_runtime_checker_without_nginx(tmp_path):
    stage = tmp_path / "stage"
    (stage / "backend" / "frontend_dist").mkdir(parents=True)
    (stage / "backend" / "scripts").mkdir(parents=True)
    (stage / "backend" / "frontend_dist" / "index.html").write_text("<html>", encoding="utf-8")
    (stage / "backend" / "scripts" / "check_backend_runtime.py").write_text("# checker", encoding="utf-8")
    (stage / "backend" / "scripts" / "start_backend.py").write_text("# launcher", encoding="utf-8")

    required = {path.relative_to(stage).as_posix() for path in release_builder.required_release_files(stage)}
    members = {path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file()}

    assert required == {
        "backend/frontend_dist/index.html",
        "backend/scripts/check_backend_runtime.py",
        "backend/scripts/start_backend.py",
    }
    assert not any(member.startswith("deploy/nginx/") for member in members)
    assert all(Path(member).is_relative_to("backend") for member in required)
