"""0006_single_general_agent

Revision ID: d3e5f6a7b8c9
Revises: c9f4a7e2d5b8
Create Date: 2026-08-16 00:00:00.000000

单通用 Agent 模型（docs 01 §3.5）：删 graph_template（多 Agent 串流模板废除），
加 is_default（标识每组织唯一通用 Agent）；subagent 由主 Agent 自主派发。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e5f6a7b8c9"
down_revision: str | None = "c9f4a7e2d5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_configs",
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.drop_column("agent_configs", "graph_template")


def downgrade() -> None:
    op.add_column(
        "agent_configs",
        sa.Column("graph_template", sa.String(length=32), server_default="single", nullable=False),
    )
    op.drop_column("agent_configs", "is_default")
