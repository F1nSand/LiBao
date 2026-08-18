"""评估领域服务（docs 03 §5.8 / docs 06 §3）。最小闭环：集/用例 CRUD + 后台运行器。

run_eval：逐 active case 独立 thread 跑 agent 图 → LLM-as-a-Judge 单次判定 → 落结果 → 更新进度。
被测对象 = 评估集所属组织下第一个已发布 agent（最小闭环；docs 06 记录 agent_version 为 M5+）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from langchain_core.messages import HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cost import estimate_cost
from app.core.errors import ERR_EVAL_CASE_NOT_FOUND, ERR_EVAL_RUN_NOT_FOUND, ERR_EVAL_SET_NOT_FOUND, AppError
from app.core.llm import LLMService
from app.orchestration.stream_core import build_initial_state, message_text
from app.services.serializers import (
    serialize_eval_case,
    serialize_eval_result,
    serialize_eval_run,
    serialize_eval_set,
)
from app.services.tool import ToolService
from app.storage.models.agent import AgentConfig
from app.storage.models.eval import EvalCase, EvalRun, EvalSet
from app.storage.models.user import User
from app.storage.repositories.eval import EvalRepository

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """你是评估裁判。判断助手回答是否达成预期（仅判断是否满足，不看风格）。
输入: {input}
预期: {expected}
助手回答: {actual}
只输出 JSON：{{"pass": true 或 false, "score": 0 到 1 的小数}}"""


class EvalService:
    # ---- 集 ----

    async def list_sets(self, db: AsyncSession, user: User) -> list[dict[str, Any]]:
        repo = EvalRepository(db)
        sets = await repo.list_sets(user.org_id)
        counts = await repo.case_counts([s.id for s in sets])
        return [serialize_eval_set(s, counts.get(s.id, 0)) for s in sets]

    async def create_set(self, db: AsyncSession, user: User, name: str, description: str | None = None) -> EvalSet:
        row = await EvalRepository(db).create_set(user.org_id, name, description)
        await db.commit()
        await db.refresh(row)
        return row

    async def get_set_owned(self, db: AsyncSession, user: User, set_id: uuid.UUID) -> EvalSet:
        row = await EvalRepository(db).get_set(user.org_id, set_id)
        if row is None:
            raise AppError(ERR_EVAL_SET_NOT_FOUND, "评估集不存在或无权访问")
        return row

    # ---- 用例 ----

    async def add_case(
        self, db: AsyncSession, user: User, set_id: uuid.UUID, input: str, expected: str, layer: str = "L3"
    ) -> EvalCase:
        s = await self.get_set_owned(db, user, set_id)
        row = await EvalRepository(db).create_case(s.id, input, expected, layer=layer)
        await db.commit()
        await db.refresh(row)
        return row

    async def list_cases(self, db: AsyncSession, user: User, set_id: uuid.UUID) -> list[dict[str, Any]]:
        s = await self.get_set_owned(db, user, set_id)
        return [serialize_eval_case(c) for c in await EvalRepository(db).list_cases(s.id)]

    async def patch_case(
        self, db: AsyncSession, user: User, set_id: uuid.UUID, case_id: uuid.UUID, active: bool
    ) -> EvalCase:
        s = await self.get_set_owned(db, user, set_id)
        repo = EvalRepository(db)
        case = await repo.get_case(case_id)
        if case is None or case.eval_set_id != s.id:
            raise AppError(ERR_EVAL_CASE_NOT_FOUND, "评估用例不存在或不属于该评估集")
        case.active = active
        await db.commit()
        await db.refresh(case)
        return case

    async def delete_case(self, db: AsyncSession, user: User, set_id: uuid.UUID, case_id: uuid.UUID) -> None:
        s = await self.get_set_owned(db, user, set_id)
        repo = EvalRepository(db)
        case = await repo.get_case(case_id)
        if case is None or case.eval_set_id != s.id:
            raise AppError(ERR_EVAL_CASE_NOT_FOUND, "评估用例不存在或不属于该评估集")
        await repo.delete_case(case_id)
        await db.commit()

    # ---- 集 ----

    async def patch_set(
        self, db: AsyncSession, user: User, set_id: uuid.UUID, name: str | None, description: str | None
    ) -> EvalSet:
        s = await self.get_set_owned(db, user, set_id)
        if name is not None:
            s.name = name
        if description is not None:
            s.description = description
        await db.commit()
        await db.refresh(s)
        return s

    async def delete_set(self, db: AsyncSession, user: User, set_id: uuid.UUID) -> None:
        s = await self.get_set_owned(db, user, set_id)
        repo = EvalRepository(db)
        if await repo.count_runs(s.id) > 0:
            raise AppError(40904, "评估集已有运行历史，不可删除（可停用用例）")
        await repo.delete_cases_for_set(s.id)  # 先删用例（无结果引用），再删集
        await repo.delete_set(s.id)
        await db.commit()

    # ---- 运行 ----

    async def create_run(
        self, db: AsyncSession, user: User, set_id: uuid.UUID, baseline_run_id: uuid.UUID | None = None
    ) -> EvalRun:
        s = await self.get_set_owned(db, user, set_id)
        row = await EvalRepository(db).create_run(s.id, baseline_run_id=baseline_run_id)
        await db.commit()
        await db.refresh(row)
        return row

    async def list_runs(self, db: AsyncSession, user: User) -> list[dict[str, Any]]:
        """运行列表：按当前用户组织收敛（org_id 过滤，越权数据不可见）。"""
        return [serialize_eval_run(r) for r in await EvalRepository(db).list_runs(org_id=user.org_id)]

    async def get_run_owned(self, db: AsyncSession, user: User, run_id: uuid.UUID) -> EvalRun:
        """取本组织运行；跨 org 一律视为不存在（40414，防存在性探测），镜像 get_set_owned。"""
        run = await EvalRepository(db).get_run(run_id, org_id=user.org_id)
        if run is None:
            raise AppError(ERR_EVAL_RUN_NOT_FOUND, "评估运行不存在或无权访问")
        return run

    async def get_run_detail(self, db: AsyncSession, user: User, run_id: uuid.UUID) -> dict[str, Any]:
        run = await self.get_run_owned(db, user, run_id)
        results = await EvalRepository(db).list_results(run_id)
        return {"run": serialize_eval_run(run), "results": [serialize_eval_result(r) for r in results]}

    async def pairwise(
        self, db: AsyncSession, user: User, run_id: uuid.UUID, baseline_run_id: uuid.UUID
    ) -> dict[str, Any]:
        """配对比较（docs 06 §2.4，McNemar 思路）：同评估集两 run 逐题比胜负。

        判断「真变好还是运气」——不是两个成功率数字谁大；一次只动一个变量。
        """
        repo = EvalRepository(db)
        run = await self.get_run_owned(db, user, run_id)
        baseline = await self.get_run_owned(db, user, baseline_run_id)
        results = await repo.list_results(run_id)
        base_results = await repo.list_results(baseline_run_id)
        base_map = {str(r.case_id): r for r in base_results}

        matrix: list[dict[str, Any]] = []
        wins = losses = ties = 0
        for cr in results:
            br = base_map.get(str(cr.case_id))
            if br is None:
                continue
            outcome = "win" if (cr.pass_ and not br.pass_) else ("lose" if (not cr.pass_ and br.pass_) else "tie")
            wins += outcome == "win"
            losses += outcome == "lose"
            ties += outcome == "tie"
            matrix.append(
                {
                    "case_id": str(cr.case_id),
                    "input": cr.input,
                    "baseline_pass": br.pass_,
                    "candidate_pass": cr.pass_,
                    "outcome": outcome,
                }
            )

        def _rate(rs: list[Any]) -> float:
            return round(sum(1 for r in rs if r.pass_) / len(rs), 4) if rs else 0.0

        base_rate = _rate(base_results)
        cand_rate = _rate(results)
        return {
            "run_id": str(run.id),
            "baseline_run_id": str(baseline.id),
            "matrix": matrix,
            "summary": {
                "baseline_pass_rate": base_rate,
                "candidate_pass_rate": cand_rate,
                "delta": round(cand_rate - base_rate, 4),
                "wins": wins,
                "losses": losses,
                "ties": ties,
            },
        }


async def run_eval(graph: Any, sessionmaker: Any, eval_run_id: uuid.UUID, model_override: Any = None) -> None:
    """后台评估链：running → 逐 active case（跑图 + LLM-judge）→ 落结果 → done + pass_rate。

    model_override 供测试注入（FakeChatModel 同时作被测模型与裁判）。
    """
    async with sessionmaker() as db:
        repo = EvalRepository(db)
        run = await repo.get_run(eval_run_id)
        if run is None:
            return
        eval_set = await _get_set_by_id(db, run.eval_set_id)
        agent = await _first_published_agent(db, eval_set.org_id) if eval_set is not None else None
        if eval_set is None or agent is None:
            run.status = "failed"
            await db.commit()
            return
        run.status = "running"
        run.progress = 0.0
        await db.commit()

        cases = await repo.list_active_cases(run.eval_set_id)
        passed_count = 0
        enabled_tool_ids = await ToolService().enabled_tool_ids(db, eval_set.org_id)
        try:
            for i, case in enumerate(cases, 1):
                actual = await _run_single_case(
                    graph, agent, case.input, str(eval_set.org_id), model_override, enabled_tool_ids
                )
                passed, score, latency_ms, cost = await _judge(case.input, case.expected, actual, model_override)
                passed_count += int(passed)
                await repo.create_result(
                    run_id=run.id, case_id=case.id, input=case.input, expected=case.expected,
                    actual=actual, pass_=passed, score=score, latency_ms=latency_ms, cost=cost,
                )
                run.progress = round(i / len(cases), 3)
                await db.commit()
            run.status = "done"
            run.pass_rate = round(passed_count / len(cases), 4) if cases else 0.0
            await db.commit()
        except Exception as exc:  # noqa: BLE001  任一 case 崩溃 → run failed（记录）
            logger.warning("eval run %s failed: %s", eval_run_id, exc)
            await db.rollback()
            run.status = "failed"
            await db.commit()


async def _get_set_by_id(db: AsyncSession, set_id: uuid.UUID) -> EvalSet | None:
    stmt = select(EvalSet).where(EvalSet.id == set_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _first_published_agent(db: AsyncSession, org_id: uuid.UUID) -> AgentConfig | None:
    stmt = (
        select(AgentConfig)
        .where(AgentConfig.org_id == org_id, AgentConfig.status == "published", AgentConfig.deleted_at.is_(None))
        .order_by(AgentConfig.created_at.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _run_single_case(
    graph: Any, agent: AgentConfig, input_text: str, org_id: str, model_override: Any, enabled_tool_ids: list[str]
) -> str:
    """单用例：独立 thread 跑一次图（values 模式取最终态）。require_confirm 工具不确认 → case 失败。"""
    initial = build_initial_state(agent, input_text, user_id=None, org_id=org_id, enabled_tool_ids=enabled_tool_ids)
    graph_config: dict[str, Any] = {"configurable": {"thread_id": f"eval-{uuid.uuid4()}"}}
    if model_override is not None:
        graph_config["configurable"]["model"] = model_override
    final_state = None
    async for item in graph.astream(initial, graph_config, stream_mode="values"):
        final_state = item
    fm = (final_state or {}).get("final_message", {}) or {}
    return str(fm.get("content", "") or "")


async def _judge(
    input_text: str, expected: str, actual: str | None, model_override: Any = None
) -> tuple[bool, float, int, float]:
    """LLM-as-a-Judge 最小闭环：单次调用判定 pass + score + latency_ms + cost；解析失败按失败计。"""
    start = time.perf_counter()
    prompt = _JUDGE_PROMPT.format(input=input_text, expected=expected, actual=(actual or "(空)")[:2000])
    try:
        model = model_override or LLMService.build_model()
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        latency_ms = int((time.perf_counter() - start) * 1000)
        usage = dict(getattr(resp, "usage_metadata", None) or {})
        model_name = getattr(resp, "response_metadata", {}).get("model", "") or ""
        cost = estimate_cost(usage, model_name or (model_override and "deepseek" or ""))
        data = _parse_judge(message_text(getattr(resp, "content", "")))
        passed = bool(data.get("pass"))
        return passed, float(data.get("score", 1.0 if passed else 0.0)), latency_ms, cost
    except Exception as exc:  # noqa: BLE001
        logger.warning("eval judge failed: %s", exc)
        return False, 0.0, int((time.perf_counter() - start) * 1000), 0.0


def _parse_judge(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    return json.loads(text[start : end + 1])
