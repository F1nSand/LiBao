"""0016_drop_memory_trace

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-22 00:00:00.000000

删除 memory_trace 表（maintenance 原料改读 messages，见 docs 04 §3.2 message-as-log）。
叶子表无反向引用，DROP 干净；downgrade 重建表 + 两索引（0004 建表 + 0007 trace_id 索引）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("memory_trace")


def downgrade() -> None:
    op.create_table(
        "memory_trace",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.UUID(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_memory_trace_user_id"), "memory_trace", ["user_id"], unique=False)
    op.create_index(op.f("ix_memory_trace_trace_id"), "memory_trace", ["trace_id"], unique=False)
