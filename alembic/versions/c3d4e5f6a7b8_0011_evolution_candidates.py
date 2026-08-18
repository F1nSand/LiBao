"""0011_evolution_candidates

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-18 00:00:00.000000

进化闭环·经验候选区表（docs 06 §5 / docs 03 §5.13）。org 级隔离；变更契约字段 + 验证结果列。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("org_id", sa.UUID(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_conversation_id", sa.UUID(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("source_type", sa.String(length=16), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("change_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'candidate'"), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("proposed_change", sa.Text(), nullable=True),
        sa.Column("expected_fix", sa.Text(), nullable=True),
        sa.Column("affected_behaviors", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("validation_cases", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_candidates_org_id"), "candidates", ["org_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_candidates_org_id"), table_name="candidates")
    op.drop_table("candidates")
