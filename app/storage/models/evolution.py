"""进化闭环·经验候选区实体（docs 06 §5 / docs 03 §5.13 / FrontEnd Candidate）。

候选 = 一条可证伪的变更契约（docs 06 §5.6）：失败证据 → 推断根因 → 候选修改 → 预期修复
→ 受损行为 → 验证用例。org 级隔离（仿 EvalSet）；验证/发布裁决由后端评估回归驱动，候选不可自改规则。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class Candidate(Base, BaseModel):
    __tablename__ = "candidates"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)  # trajectory/eval/manual
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)  # prompt/skill/tool/memory/context
    status: Mapped[str] = mapped_column(String(16), default="candidate", nullable=False)  # 见 CANDIDATE_TRANSITIONS

    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败证据
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)  # 推断根因
    proposed_change: Mapped[str | None] = mapped_column(Text, nullable=True)  # prompt 型 = 新 system_prompt
    expected_fix: Mapped[str | None] = mapped_column(Text, nullable=True)  # 预期修复
    affected_behaviors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # 受损行为
    validation_cases: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # [{input, expected}]

    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # validate 结果
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
