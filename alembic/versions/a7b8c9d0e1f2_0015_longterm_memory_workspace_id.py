"""0015_longterm_memory_workspace_id

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-20 00:00:00.000000

长期记忆加 workspace_id（M7-B 工作区记忆隔离）；null=个人记忆。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("longterm_memory", sa.Column("workspace_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("longterm_memory", "workspace_id")
