"""一次性清理脚本：删除测试污染数据（除「默认组织」外的所有 org 及其全部关联），保留默认组织。

背景（详见 plans 存档）：测试用共享真实 DB（tests/conftest.py `requires_db` 只探测端口可达，
无 DB 隔离/事务回滚/teardown 清理），每个 DB-backed 测试文件创建 org 后从不删除，且命名不统一
（测试组织-* / org2-* / dbg-* / diag-* / evo隔离-* / conc-* …）→ 累积数千行，导致启动全量同步
`sync_registry_from_db` 对每个 MCP 行逐个查 mcp_servers（N+1）而卡死。
seed 只创建「默认组织」这一个真实 org，其余 org 全是测试/隔离用例垃圾 → 按「非默认组织」删除。

用法（在项目根 Agent/ 下）：
  uv run python scripts/cleanup_test_orgs.py --dry-run   # 预览各表删除行数（事务回滚，不实际删）
  uv run python scripts/cleanup_test_orgs.py             # 正式清理（单事务提交）

删除原则：所有 FK 均为 NO ACTION（无级联），必须严格按「叶子 → 根」逆依赖序；
先物化各层 id 到 Python list（避免删除过程中子查询被清空），再逐表 DELETE。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 脚本位于 scripts/（非包），直接 `python scripts/xxx.py` 运行时 sys.path[0] 是 scripts/，
# 需把项目根加入 sys.path 才能 import app.*（seed 用 `-m app.seed` 无此问题）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.db import init_db
from app.storage.models import (
    AgentConfig,
    AgentVersion,
    Attachment,
    Candidate,
    Conversation,
    EvalCase,
    EvalResult,
    EvalRun,
    EvalSet,
    KbChunk,
    KbCollection,
    KbDocument,
    LongTermMemory,
    LongTermMemoryVersion,
    McpServer,
    Message,
    Notification,
    Org,
    ProviderConfig,
    RunLog,
    Skill,
    Task,
    ToolDefinition,
    User,
    WebhookConfig,
    Workspace,
)

DEFAULT_ORG_NAME = "默认组织"


async def _scalars(session: AsyncSession, stmt) -> list:
    return list((await session.execute(stmt)).scalars())


async def main(dry_run: bool) -> None:
    engine, sessionmaker = init_db()
    async with sessionmaker() as session:
        # ---- 1. 物化各层目标 id（在删除任何数据前，全部取成 Python list）----
        # 保留「默认组织」，删除其余所有 org（seed 只建默认组织，其余全是测试/隔离用例垃圾）。
        org_ids = await _scalars(session, select(Org.id).where(Org.name != DEFAULT_ORG_NAME))
        if not org_ids:
            print("除默认组织外无其他 org，无需清理。")
            return

        user_ids = await _scalars(session, select(User.id).where(User.org_id.in_(org_ids)))
        conv_ids = await _scalars(session, select(Conversation.id).where(Conversation.user_id.in_(user_ids)))
        set_ids = await _scalars(session, select(EvalSet.id).where(EvalSet.org_id.in_(org_ids)))
        run_ids = await _scalars(session, select(EvalRun.id).where(EvalRun.eval_set_id.in_(set_ids)))
        case_ids = await _scalars(session, select(EvalCase.id).where(EvalCase.eval_set_id.in_(set_ids)))
        coll_ids = await _scalars(session, select(KbCollection.id).where(KbCollection.org_id.in_(org_ids)))
        mem_ids = await _scalars(session, select(LongTermMemory.id).where(LongTermMemory.user_id.in_(user_ids)))
        task_ids = await _scalars(session, select(Task.id).where(Task.user_id.in_(user_ids)))
        agent_ids = await _scalars(session, select(AgentConfig.id).where(AgentConfig.org_id.in_(org_ids)))

        print(
            f"目标：org={len(org_ids)} user={len(user_ids)} conv={len(conv_ids)} "
            f"eval_set={len(set_ids)} eval_run={len(run_ids)} eval_case={len(case_ids)} "
            f"kb_collection={len(coll_ids)} mem={len(mem_ids)} task={len(task_ids)} agent={len(agent_ids)}"
        )

        # ---- 2. 逆依赖序 DELETE（叶子 → 根）----
        deletes: list[tuple[str, object]] = [
            ("eval_results", delete(EvalResult).where(
                or_(EvalResult.run_id.in_(run_ids), EvalResult.case_id.in_(case_ids))
            )),
            ("eval_runs", delete(EvalRun).where(EvalRun.id.in_(run_ids))),
            ("eval_cases", delete(EvalCase).where(EvalCase.id.in_(case_ids))),
            ("eval_sets", delete(EvalSet).where(EvalSet.id.in_(set_ids))),
            ("kb_chunks", delete(KbChunk).where(KbChunk.org_id.in_(org_ids))),
            ("kb_documents", delete(KbDocument).where(KbDocument.org_id.in_(org_ids))),
            ("kb_collections", delete(KbCollection).where(KbCollection.id.in_(coll_ids))),
            ("longterm_memory_version", delete(LongTermMemoryVersion).where(
                LongTermMemoryVersion.memory_id.in_(mem_ids)
            )),
            ("longterm_memory", delete(LongTermMemory).where(LongTermMemory.id.in_(mem_ids))),
            ("messages", delete(Message).where(Message.conversation_id.in_(conv_ids))),
            ("run_logs", delete(RunLog).where(
                or_(RunLog.session_id.in_(conv_ids), RunLog.task_id.in_(task_ids))
            )),
            ("attachments", delete(Attachment).where(
                or_(Attachment.conversation_id.in_(conv_ids), Attachment.user_id.in_(user_ids))
            )),
            ("webhook_configs", delete(WebhookConfig).where(
                or_(WebhookConfig.conversation_id.in_(conv_ids), WebhookConfig.org_id.in_(org_ids))
            )),
            ("candidates", delete(Candidate).where(
                or_(Candidate.source_conversation_id.in_(conv_ids), Candidate.org_id.in_(org_ids))
            )),
            ("conversations", delete(Conversation).where(Conversation.user_id.in_(user_ids))),
            ("notifications", delete(Notification).where(Notification.user_id.in_(user_ids))),
            ("tasks", delete(Task).where(Task.user_id.in_(user_ids))),
            ("agent_versions", delete(AgentVersion).where(AgentVersion.agent_id.in_(agent_ids))),
            ("users", delete(User).where(User.org_id.in_(org_ids))),
            ("tool_definitions", delete(ToolDefinition).where(ToolDefinition.org_id.in_(org_ids))),
            ("mcp_servers", delete(McpServer).where(McpServer.org_id.in_(org_ids))),
            ("skills", delete(Skill).where(Skill.org_id.in_(org_ids))),
            ("workspaces", delete(Workspace).where(Workspace.org_id.in_(org_ids))),
            ("agent_configs", delete(AgentConfig).where(AgentConfig.org_id.in_(org_ids))),
            ("provider_configs", delete(ProviderConfig).where(ProviderConfig.org_id.in_(org_ids))),
            ("orgs", delete(Org).where(Org.id.in_(org_ids))),
        ]

        # ---- 3. 执行（dry-run 则回滚）----
        for name, stmt in deletes:
            result = await session.execute(stmt)
            print(f"  {name}: {result.rowcount} 行")

        if dry_run:
            await session.rollback()
            print("（--dry-run：已回滚，未实际删除）")
        else:
            await session.commit()
            print("已提交删除。")

        # ---- 4. 清理后自检：默认组织数据应完好 ----
        default_org = (
            await session.execute(select(Org).where(Org.name == DEFAULT_ORG_NAME))
        ).scalar_one_or_none()
        if default_org is not None:
            users = await _scalars(session, select(User.id).where(User.org_id == default_org.id))
            tools = await _scalars(session, select(ToolDefinition.id).where(ToolDefinition.org_id == default_org.id))
            mcp = await _scalars(session, select(McpServer.id).where(McpServer.org_id == default_org.id))
            print(f"自检：默认组织保留 user={len(users)} tool={len(tools)} mcp={len(mcp)}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
