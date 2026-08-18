"""进化闭环·候选区领域服务（docs 06 §5 / docs 03 §5.13）。

闭环「候选→验证→发布/回滚」段。验证规则（阈值/判定）为代码常量，候选 payload 不可自改
（docs 06 §5.5 安全边界）；发布只支持 prompt 载体（proposed_change 写入 AgentConfig.system_prompt）。
"""
from __future__ import annotations

import copy
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_CANDIDATE_CARRIER_UNSUPPORTED,
    ERR_CANDIDATE_NO_CASES,
    ERR_CANDIDATE_STATE_INVALID,
    ERR_CONVERSATION_NOT_FOUND,
    AppError,
)
from app.services.agent import AgentService
from app.services.eval import _judge, _run_single_case
from app.services.tool import ToolService
from app.storage.models.evolution import Candidate
from app.storage.models.user import User
from app.storage.repositories.evolution import EvolutionRepository

logger = logging.getLogger(__name__)

# 状态迁移（仿前端 mock）：action → 允许的起始状态集
CANDIDATE_TRANSITIONS: dict[str, set[str]] = {
    "validate": {"candidate"},
    "reject": {"candidate"},
    "publish": {"approved"},
    "rollback": {"published"},
}

CANDIDATE_PASS_THRESHOLD = 0.8


def _assert_transition(action: str, candidate: Candidate) -> None:
    if candidate.status not in CANDIDATE_TRANSITIONS.get(action, ()):
        raise AppError(ERR_CANDIDATE_STATE_INVALID, f"候选状态 {candidate.status} 不允许 {action}")


class EvolutionService:
    # ---- 查询 ----

    async def list_candidates(
        self,
        db: AsyncSession,
        user: User,
        *,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        repo = EvolutionRepository(db)
        items, total = await repo.list_candidates(
            user.org_id, status=status, search=search, limit=page_size, offset=(page - 1) * page_size
        )
        from app.api.schemas.common import paged

        return paged([serialize_candidate(c) for c in items], total, page, page_size)

    async def get_candidate_owned(self, db: AsyncSession, user: User, candidate_id: uuid.UUID) -> Candidate:
        candidate = await EvolutionRepository(db).get_owned(user.org_id, candidate_id)
        if candidate is None:
            raise AppError(ERR_CONVERSATION_NOT_FOUND, "候选不存在或无权访问")
        return candidate

    # ---- 创建（手动入口，source_type=manual）----

    async def create_candidate(
        self,
        db: AsyncSession,
        user: User,
        *,
        title: str,
        change_type: str,
        evidence: str | None = None,
        root_cause: str | None = None,
        proposed_change: str | None = None,
        expected_fix: str | None = None,
        affected_behaviors: list | None = None,
        validation_cases: list | None = None,
    ) -> Candidate:
        repo = EvolutionRepository(db)
        row = await repo.create(
            org_id=user.org_id,
            title=title,
            change_type=change_type,
            source_type="manual",
            evidence=evidence,
            root_cause=root_cause,
            proposed_change=proposed_change,
            expected_fix=expected_fix,
            affected_behaviors=affected_behaviors,
            validation_cases=validation_cases,
        )
        await db.commit()
        await db.refresh(row)
        return row

    # ---- 状态动作 ----

    async def validate_candidate(
        self, db: AsyncSession, user: User, candidate_id: uuid.UUID, graph: Any, model_override: Any = None
    ) -> Candidate:
        """同步验证：逐 validation_case 跑候选快照 agent → LLM judge → pass_rate → approved/rejected。

        契约要求同步返回（前端不轮询）；10-30s 真实 LLM 可接受。单 case 异常判失败，不中断。
        """
        candidate = await self.get_candidate_owned(db, user, candidate_id)
        _assert_transition("validate", candidate)

        cases = candidate.validation_cases or []
        if not cases:
            raise AppError(ERR_CANDIDATE_NO_CASES, "候选没有验证用例，无法验证")

        agent = await AgentService().get_default(db, user.org_id)
        # 候选快照（瞬态，不入 session）：prompt 型用 proposed_change 替换 system_prompt
        snapshot = copy.copy(agent)
        if candidate.change_type == "prompt":
            snapshot.system_prompt = candidate.proposed_change
        enabled_tool_ids = await ToolService().enabled_tool_ids(db, user.org_id)

        passed = 0
        for case in cases:
            try:
                actual = await _run_single_case(
                    graph, snapshot, case["input"], str(user.org_id), model_override, enabled_tool_ids
                )
                ok_case, _score, _latency, _cost = await _judge(
                    case["input"], case.get("expected", ""), actual, model_override
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("candidate %s case failed: %s", candidate_id, exc)
                ok_case = False
            passed += int(ok_case)

        candidate.pass_rate = round(passed / len(cases), 4)
        candidate.validated_at = datetime.now(UTC)
        candidate.status = "approved" if candidate.pass_rate >= CANDIDATE_PASS_THRESHOLD else "rejected"
        await db.commit()
        await db.refresh(candidate)
        return candidate

    async def reject_candidate(self, db: AsyncSession, user: User, candidate_id: uuid.UUID) -> Candidate:
        candidate = await self.get_candidate_owned(db, user, candidate_id)
        _assert_transition("reject", candidate)
        candidate.status = "rejected"
        await db.commit()
        await db.refresh(candidate)
        return candidate

    async def publish_candidate(self, db: AsyncSession, user: User, candidate_id: uuid.UUID) -> Candidate:
        candidate = await self.get_candidate_owned(db, user, candidate_id)
        _assert_transition("publish", candidate)
        if candidate.change_type != "prompt":
            raise AppError(
                ERR_CANDIDATE_CARRIER_UNSUPPORTED, "仅 prompt 型候选可发布（tool/skill/memory/context 载体未实现）"
            )
        if not candidate.proposed_change:
            raise AppError(ERR_CANDIDATE_CARRIER_UNSUPPORTED, "候选缺少 proposed_change（新 system_prompt）")
        # 单事务：agent 更新 + candidate 状态
        await AgentService().publish_prompt(db, user.org_id, candidate.proposed_change)
        candidate.status = "published"
        await db.commit()
        await db.refresh(candidate)
        return candidate

    async def rollback_candidate(self, db: AsyncSession, user: User, candidate_id: uuid.UUID) -> Candidate:
        candidate = await self.get_candidate_owned(db, user, candidate_id)
        _assert_transition("rollback", candidate)
        # 仅当前生效的候选可回滚（否则会错误撤销更晚发布的候选）
        agent = await AgentService().get_default(db, user.org_id)
        if candidate.proposed_change != agent.system_prompt:
            raise AppError(ERR_CANDIDATE_STATE_INVALID, "该候选不是当前生效版本，无法回滚")
        # 单事务：agent 回滚 + candidate 状态
        await AgentService().rollback_prompt(db, user.org_id)
        candidate.status = "rolled_back"
        await db.commit()
        await db.refresh(candidate)
        return candidate


def serialize_candidate(c: Candidate) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "title": c.title,
        "source_conversation_id": str(c.source_conversation_id) if c.source_conversation_id else None,
        "source_type": c.source_type,
        "change_type": c.change_type,
        "status": c.status,
        "evidence": c.evidence,
        "root_cause": c.root_cause,
        "proposed_change": c.proposed_change,
        "expected_fix": c.expected_fix,
        "affected_behaviors": c.affected_behaviors or [],
        "validation_cases": _serialize_validation_cases(c.validation_cases or []),
        "pass_rate": c.pass_rate,
        "validated_at": _dt(c.validated_at),
        "created_at": _dt(c.created_at),
        "updated_at": _dt(c.updated_at),
    }


def _serialize_validation_cases(cases: list) -> list[str]:
    """结构化 [{input, expected}] → 可读 string[]（前端契约 validation_cases: string[]，join 渲染）。"""
    out: list[str] = []
    for case in cases:
        if isinstance(case, str):
            out.append(case)
        elif isinstance(case, dict) and case.get("input"):
            expected = case.get("expected")
            out.append(f"输入「{case['input']}」应：{expected}" if expected else f"输入「{case['input']}」")
        else:
            out.append(str(case))
    return out


def _dt(v: datetime | None) -> str | None:
    return v.isoformat() if v else None
