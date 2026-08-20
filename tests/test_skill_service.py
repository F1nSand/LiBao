"""M7-A skill 服务层测试：解析、默认关闭、重名 40907、启停、软删、git 导入。

需要 Docker db（localhost:5432）；DB 不可达自动跳过。
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from app.api.schemas.skill import CreateSkillRequest
from app.core.errors import AppError
from app.core.security import hash_password
from app.services.serializers import serialize_skill
from app.services.skill import SkillService, parse_skill_md
from app.storage.db import init_db
from app.storage.models import Org, User
from app.tools.builtin import register_builtin_tools
from tests.conftest import requires_db

pytestmark = requires_db

VALID_SKILL = """---
name: kb_strategy
description: 当需从知识库检索资料时用。反例：闲聊。
---
# 步骤
1. 调 kb_search 检索。
"""


def test_parse_skill_md_valid():
    parsed = parse_skill_md(VALID_SKILL)
    assert parsed["name"] == "kb_strategy"
    assert "知识库" in parsed["description"]
    assert "# 步骤" in parsed["body"]


def test_parse_skill_md_missing_description():
    with pytest.raises(AppError) as exc:
        parse_skill_md("---\nname: x\n---\nbody")
    assert exc.value.code == 40024


def test_parse_skill_md_no_frontmatter():
    with pytest.raises(AppError) as exc:
        parse_skill_md("# 没有 frontmatter\n正文")
    assert exc.value.code == 40024


@pytest.fixture
async def skill_fixture():
    register_builtin_tools()
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-skills-{uid}")
        session.add(org)
        await session.flush()
        user = User(
            username=f"skills_{uid}", password_hash=hash_password("x"), name="S", role="admin", org_id=org.id
        )
        session.add(user)
        await session.commit()
    yield sessionmaker, user
    await engine.dispose()


async def test_create_skill_default_disabled(skill_fixture):
    sessionmaker, user = skill_fixture
    async with sessionmaker() as session:
        row = await SkillService().create(
            session, user, CreateSkillRequest(name="kb_strategy", description="检索", body="# 步骤")
        )
        data = serialize_skill(row)
        assert data["enabled"] is False  # 默认关闭
        assert data["name"] == "kb_strategy"
        assert data["source"] == "manual"


async def test_create_duplicate_name_conflict(skill_fixture):
    sessionmaker, user = skill_fixture
    async with sessionmaker() as session:
        await SkillService().create(session, user, CreateSkillRequest(name="dup"))
        with pytest.raises(AppError) as exc:
            await SkillService().create(session, user, CreateSkillRequest(name="dup"))
        assert exc.value.code == 40907


async def test_set_enabled_and_list_filter(skill_fixture):
    sessionmaker, user = skill_fixture
    async with sessionmaker() as session:
        await SkillService().create(session, user, CreateSkillRequest(name="s1"))
        row = await SkillService().create(session, user, CreateSkillRequest(name="s2"))
        await SkillService().set_enabled(session, user, str(row.id), True)
        # enabled 过滤
        enabled = await SkillService().list_for_org(session, user.org_id, 1, 50, enabled=True)
        assert [s["name"] for s in enabled["items"]] == ["s2"]
        all_items = await SkillService().list_for_org(session, user.org_id, 1, 50)
        assert all_items["total"] == 2


async def test_soft_delete(skill_fixture):
    sessionmaker, user = skill_fixture
    async with sessionmaker() as session:
        row = await SkillService().create(session, user, CreateSkillRequest(name="gone"))
        await SkillService().soft_delete(session, user, str(row.id))
        with pytest.raises(AppError) as exc:
            await SkillService().get_in_org(session, user.org_id, str(row.id))
        assert exc.value.code == 40415


def _make_local_skill_repo(tmp_path: Path) -> str:
    """建一个含 1 合法 + 1 非法 SKILL.md 的本地 git 仓库，返回路径。"""
    repo = tmp_path / "skills-repo"
    skills = repo / "skills"
    (skills / "good").mkdir(parents=True)
    (skills / "bad").mkdir(parents=True)
    (skills / "good" / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
    (skills / "bad" / "SKILL.md").write_text("no frontmatter", encoding="utf-8")

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)

    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "test")
    _git("add", ".")
    _git("commit", "-m", "init")
    return str(repo)


async def test_import_from_git_local(skill_fixture, tmp_path):
    """本地 git 仓库导入：合法 skill 入库、非法跳过。git 不可用则跳过。"""
    try:
        repo_path = _make_local_skill_repo(tmp_path)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git 不可用，跳过导入测试")

    sessionmaker, user = skill_fixture
    async with sessionmaker() as session:
        result = await SkillService().import_from_git(session, user, repo_path)
        assert result["imported"] == 1  # good 入库，bad 跳过
        items = await SkillService().list_for_org(session, user.org_id, 1, 50)
        names = {s["name"] for s in items["items"]}
        assert "kb_strategy" in names
        row = await SkillService().get_in_org(session, user.org_id, "kb_strategy")
        assert row.source == "git"
