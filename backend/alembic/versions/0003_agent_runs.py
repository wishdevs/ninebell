"""add agent_runs (라이브 실행 요약·이력)

Revision ID: 0003_agent_runs
Revises: 0002_user_local_auth
Create Date: 2026-07-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_agent_runs"
down_revision: str | None = "0002_user_local_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        # 클라이언트가 만든 런 id(세션 키와 동일).
        sa.Column("id", sa.String(length=40), nullable=False),
        # 워크플로우 식별자(FK 아님 — demo-echo 등 미등록 워크플로우 허용).
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("logs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_agent_runs_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs"),
    )
    op.create_index("ix_agent_runs_agent_id", "agent_runs", ["agent_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_id", table_name="agent_runs")
    op.drop_table("agent_runs")
