"""0007_m5_eval_obs_hooks

Revision ID: e7f8a9b0c1d2
Revises: d3e5f6a7b8c9
Create Date: 2026-08-17 00:00:00.000000

M5 评估与观测 + M6 前开放项：
- eval_cases 加 layer（L1-L5 分层，docs 06 §3.1）
- eval_runs 加 baseline_run_id（配对比较，docs 06 §2.4）
- webhook_configs 新表（docs 03 §5.10 hooks/webhook）
- run_logs 加 created_at/status/type 索引、memory_trace.trace_id 索引（观测查询提速）
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d3e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- M5 评估 ----
    op.add_column("eval_cases", sa.Column("layer", sa.String(length=8), server_default="L3", nullable=False))
    op.add_column(
        "eval_runs",
        sa.Column("baseline_run_id", sa.UUID(), sa.ForeignKey("eval_runs.id"), nullable=True),
    )

    # ---- hooks/webhook（docs 03 §5.10）----
    op.create_table(
        "webhook_configs",
        sa.Column("org_id", sa.UUID(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("tool_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.UUID(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_webhook_configs_org_id"), "webhook_configs", ["org_id"], unique=False)

    # ---- 观测索引（M5 增长查询）----
    op.create_index(op.f("ix_run_logs_created_at"), "run_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_run_logs_status"), "run_logs", ["status"], unique=False)
    op.create_index(op.f("ix_run_logs_type"), "run_logs", ["type"], unique=False)
    op.create_index(op.f("ix_memory_trace_trace_id"), "memory_trace", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_memory_trace_trace_id"), table_name="memory_trace")
    op.drop_index(op.f("ix_run_logs_type"), table_name="run_logs")
    op.drop_index(op.f("ix_run_logs_status"), table_name="run_logs")
    op.drop_index(op.f("ix_run_logs_created_at"), table_name="run_logs")
    op.drop_index(op.f("ix_webhook_configs_org_id"), table_name="webhook_configs")
    op.drop_table("webhook_configs")
    op.drop_column("eval_runs", "baseline_run_id")
    op.drop_column("eval_cases", "layer")
