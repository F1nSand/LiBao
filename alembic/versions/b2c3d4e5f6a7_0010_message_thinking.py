"""0010_message_thinking

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-17 00:00:00.000000

逐轮消息契约补 thinking（docs 03 §3）：messages 加 thinking 列（每轮推理文本，reasoning_content）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("thinking", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "thinking")
