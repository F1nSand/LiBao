"""0009_message_round

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-17 00:00:00.000000

逐轮消息契约（docs 03 §3 多消息扩展）：messages 加 round 列（轮次序号，同 commit 排序稳定）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("round", sa.Integer(), server_default="1", nullable=False))


def downgrade() -> None:
    op.drop_column("messages", "round")
