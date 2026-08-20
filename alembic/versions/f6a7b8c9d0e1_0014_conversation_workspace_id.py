"""0014_conversation_workspace_id

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-20 00:00:00.000000

会话加 workspace_id（M7-B 工作区对话）；无 FK（软删/清理顺序耦合，见 conversation model 注释）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("workspace_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "workspace_id")
