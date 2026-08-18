"""M6-2 进化闭环·候选区测试（DB-backed）：CRUD/状态机/同步 validate/发布回滚。"""
from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.core.errors import AppError
from app.core.security import hash_password
from app.orchestration.graph import build_graph
from app.services.agent import AgentService
from app.services.evolution import EvolutionService
from app.storage.db import init_db
from app.storage.models import AgentConfig, AgentVersion, Org, User
from tests.conftest import requires_db

pytestmark = requires_db


class FakeEvalModel:
    """同一模型实例同时作被测模型与裁判（按 prompt 分支）。captured 记录被测阶段上下文文本。"""

    def __init__(self, judge_pass: bool = True, content: str = "这是候选回答。"):
        self.judge_pass = judge_pass
        self.content = content
        self.captured: list[str] = []

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        text = "".join(str(getattr(m, "content", "") or "") for m in messages)
        if "你是评估裁判" in text:
            return AIMessage(content=json.dumps({"pass": self.judge_pass, "score": 0.9 if self.judge_pass else 0.0}))
        self.captured.append(text)
        return AIMessage(content=self.content)


@pytest.fixture
async def evo_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-evo-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"evo_{uid}", password_hash=hash_password("x"), name="E", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="通用助手", model="fake", system_prompt="原始提示词", tools=[],
            max_steps=5, status="published", is_default=True, current_version=1,
        )
        session.add(agent)
        await session.flush()
        session.add(
            AgentVersion(
                agent_id=agent.id, version=1, system_prompt="原始提示词", model="fake",
                tools=[], skills=[], prefix_hash="seed-hash",
            )
        )
        await session.commit()
    yield sessionmaker, user
    await engine.dispose()


async def _make_candidate(
    svc, session, user, *, change_type="prompt", status=None, cases=None, prompt="新提示词", title=None
):
    c = await svc.create_candidate(
        session, user, title=title or f"候选-{uuid.uuid4().hex[:6]}", change_type=change_type,
        proposed_change=prompt, validation_cases=cases,
    )
    if status is not None:
        # 直接落库改状态（跳过状态机，测试特定状态前置）
        from app.storage.repositories.evolution import EvolutionRepository
        row = await EvolutionRepository(session).get_owned(user.org_id, c.id)
        row.status = status
        await session.commit()
        await session.refresh(row)
        c = row
    return c


# ---- CRUD + 过滤 ----

async def test_candidate_create_list_filter(evo_fixture):
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    async with sessionmaker() as session:
        await _make_candidate(svc, session, user, title="数学提示词", prompt="数学提示词内容")
        await _make_candidate(svc, session, user, title="安全护栏", status="published", prompt="安全护栏内容")
        data = await svc.list_candidates(session, user, page=1, page_size=20)
        assert data["total"] >= 2
        # status 精确过滤
        pub = await svc.list_candidates(session, user, status="published", page=1, page_size=20)
        assert all(it["status"] == "published" for it in pub["items"])
        # search 仅 title 包含
        hits = await svc.list_candidates(session, user, search="数学", page=1, page_size=20)
        assert all("数学" in it["title"] for it in hits["items"])
        assert hits["total"] >= 1


# ---- 状态机 ----

async def test_state_machine_transitions(evo_fixture):
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    graph = build_graph()
    async with sessionmaker() as session:
        c = await _make_candidate(svc, session, user, cases=[{"input": "1+1", "expected": "2"}])
        # validate → approved（Fake judge pass）
        approved = await svc.validate_candidate(session, user, c.id, graph, FakeEvalModel(judge_pass=True))
        assert approved.status == "approved"
        # publish → published
        published = await svc.publish_candidate(session, user, c.id)
        assert published.status == "published"
        # rollback → rolled_back
        rolled = await svc.rollback_candidate(session, user, c.id)
        assert rolled.status == "rolled_back"


async def test_state_machine_invalid_edges(evo_fixture):
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    async with sessionmaker() as session:
        cand = await _make_candidate(svc, session, user)
        # publish candidate（未 approved）→ 40020
        with pytest.raises(AppError) as exc:
            await svc.publish_candidate(session, user, cand.id)
        assert exc.value.code == 40020
        # rollback candidate → 40020
        with pytest.raises(AppError) as exc:
            await svc.rollback_candidate(session, user, cand.id)
        assert exc.value.code == 40020


# ---- 同步 validate ----

async def test_validate_sync_approve_and_reject(evo_fixture):
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    graph = build_graph()
    async with sessionmaker() as session:
        cases = [{"input": "1+1", "expected": "2"}, {"input": "2+2", "expected": "4"}]
        c_ok = await _make_candidate(svc, session, user, cases=cases)
        ok = await svc.validate_candidate(session, user, c_ok.id, graph, FakeEvalModel(judge_pass=True))
        assert ok.status == "approved" and ok.pass_rate == 1.0

        c_bad = await _make_candidate(svc, session, user, cases=cases)
        bad = await svc.validate_candidate(session, user, c_bad.id, graph, FakeEvalModel(judge_pass=False))
        assert bad.status == "rejected" and bad.pass_rate == 0.0


async def test_validate_uses_candidate_prompt(evo_fixture):
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    graph = build_graph()
    async with sessionmaker() as session:
        prompt = "候选专属提示词XYZ"
        c = await _make_candidate(svc, session, user, prompt=prompt, cases=[{"input": "1+1", "expected": "2"}])
        model = FakeEvalModel(judge_pass=True)
        await svc.validate_candidate(session, user, c.id, graph, model)
        assert any(prompt in t for t in model.captured), "被测阶段应使用候选 system_prompt"


async def test_validate_empty_cases(evo_fixture):
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    graph = build_graph()
    async with sessionmaker() as session:
        c = await _make_candidate(svc, session, user, cases=None)
        with pytest.raises(AppError) as exc:
            await svc.validate_candidate(session, user, c.id, graph, FakeEvalModel())
        assert exc.value.code == 40022


# ---- 发布/回滚 ----

async def test_publish_prompt_only(evo_fixture):
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    graph = build_graph()
    async with sessionmaker() as session:
        # tool 载体 → 40021
        tool_c = await _make_candidate(svc, session, user, change_type="tool")
        tool_c.status = "approved"
        await session.commit()
        with pytest.raises(AppError) as exc:
            await svc.publish_candidate(session, user, tool_c.id)
        assert exc.value.code == 40021

        # prompt 载体 → 发布成功 + 单事务
        prompt = "新发布提示词ABC"
        p_c = await _make_candidate(svc, session, user, prompt=prompt, cases=[{"input": "1+1", "expected": "2"}])
        p_c = await svc.validate_candidate(session, user, p_c.id, graph, FakeEvalModel(judge_pass=True))
        pub = await svc.publish_candidate(session, user, p_c.id)
        assert pub.status == "published"
        agent = await AgentService().get_default(session, user.org_id)
        assert agent.system_prompt == prompt
        assert agent.current_version == 2


async def test_rollback_rejects_non_current_candidate(evo_fixture):
    """回滚非当前生效候选 → 40020（防错误撤销更晚发布的候选）。"""
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    graph = build_graph()
    async with sessionmaker() as session:
        # 发布 A（生效），再发布 B（覆盖 A）
        a = await _make_candidate(svc, session, user, title="A", prompt="提示词A",
                                  cases=[{"input": "1+1", "expected": "2"}])
        a = await svc.validate_candidate(session, user, a.id, graph, FakeEvalModel(judge_pass=True))
        await svc.publish_candidate(session, user, a.id)
        b = await _make_candidate(svc, session, user, title="B", prompt="提示词B",
                                  cases=[{"input": "1+1", "expected": "2"}])
        b = await svc.validate_candidate(session, user, b.id, graph, FakeEvalModel(judge_pass=True))
        await svc.publish_candidate(session, user, b.id)
        # A 已非当前生效 → rollback A 拒绝
        with pytest.raises(AppError) as exc:
            await svc.rollback_candidate(session, user, a.id)
        assert exc.value.code == 40020
        # B 当前生效 → rollback B 成功
        rolled = await svc.rollback_candidate(session, user, b.id)
        assert rolled.status == "rolled_back"


async def test_rollback_restores_previous_prompt(evo_fixture):
    sessionmaker, user = evo_fixture
    svc = EvolutionService()
    graph = build_graph()
    async with sessionmaker() as session:
        prompt = "新提示词XYZ"
        c = await _make_candidate(svc, session, user, prompt=prompt, cases=[{"input": "1+1", "expected": "2"}])
        c = await svc.validate_candidate(session, user, c.id, graph, FakeEvalModel(judge_pass=True))
        await svc.publish_candidate(session, user, c.id)
        rolled = await svc.rollback_candidate(session, user, c.id)
        assert rolled.status == "rolled_back"
        agent = await AgentService().get_default(session, user.org_id)
        assert agent.system_prompt == "原始提示词"  # 恢复 v1
        assert agent.current_version == 3  # v2 失败快照保留，回滚再 +1
