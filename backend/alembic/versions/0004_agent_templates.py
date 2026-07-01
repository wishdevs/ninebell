"""add agent_templates (대화형 selections 저장·재생 템플릿)

Revision ID: 0004_agent_templates
Revises: 0003_agent_runs
Create Date: 2026-07-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_agent_templates"
down_revision: str | None = "0003_agent_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_templates",
        # 클라이언트가 만든 템플릿 id(예: 'tpl-<hex>').
        sa.Column("id", sa.String(length=40), nullable=False),
        # 워크플로우 식별자(FK 아님 — agent_runs 와 동일한 느슨한 문자열).
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("selections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_agent_templates_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_templates"),
    )
    op.create_index("ix_agent_templates_agent_id", "agent_templates", ["agent_id"])
    op.create_index("ix_agent_templates_user_id", "agent_templates", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_templates_user_id", table_name="agent_templates")
    op.drop_index("ix_agent_templates_agent_id", table_name="agent_templates")
    op.drop_table("agent_templates")
