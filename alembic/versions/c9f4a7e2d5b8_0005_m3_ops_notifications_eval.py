"""0005_m3_ops_notifications_eval

Revision ID: c9f4a7e2d5b8
Revises: 57d22824e0e5
Create Date: 2026-08-16 00:00:00.000000

M3 收尾：notifications 表 + 评估四表（eval_set/case/run/result，docs 04 §3.9 最小闭环）。
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f4a7e2d5b8"
down_revision: str | None = "57d22824e0e5"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ---- 通知 ----
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)

    # ---- 评估 ----
    op.create_table(
        "eval_sets",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("org_id", sa.UUID(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_eval_sets_org_id"), "eval_sets", ["org_id"], unique=False)

    op.create_table(
        "eval_cases",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("eval_set_id", sa.UUID(), sa.ForeignKey("eval_sets.id"), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_eval_cases_eval_set_id"), "eval_cases", ["eval_set_id"], unique=False)

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("eval_set_id", sa.UUID(), sa.ForeignKey("eval_sets.id"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("progress", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_eval_runs_eval_set_id"), "eval_runs", ["eval_set_id"], unique=False)

    op.create_table(
        "eval_results",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("run_id", sa.UUID(), sa.ForeignKey("eval_runs.id"), nullable=False),
        sa.Column("case_id", sa.UUID(), sa.ForeignKey("eval_cases.id"), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("actual", sa.Text(), nullable=True),
        sa.Column("pass", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_eval_results_run_id"), "eval_results", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_eval_results_run_id"), table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index(op.f("ix_eval_runs_eval_set_id"), table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index(op.f("ix_eval_cases_eval_set_id"), table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_index(op.f("ix_eval_sets_org_id"), table_name="eval_sets")
    op.drop_table("eval_sets")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
