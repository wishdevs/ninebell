"""agent_groups — 에이전트 그룹(2뎁스 분류) 테이블 + agents.group_id

Revision ID: 0016_agent_groups
Revises: 0015_agent_step_phase
Create Date: 2026-07-05

그룹은 실행 불가한 순수 분류/내비 단위 — 실행 allowlist·조직접근·즐겨찾기·런 기록은
전부 에이전트 단위 무변경. 그룹 삭제 시 소속 에이전트는 단독(group_id NULL)으로 승격.
그룹·소속 시드는 멱등 시드(seed_agent_groups/seed_agents)가 처리한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_agent_groups"
down_revision: str | None = "0015_agent_step_phase"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_groups",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agents",
        sa.Column(
            "group_id",
            sa.String(length=64),
            sa.ForeignKey("agent_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "group_id")
    op.drop_table("agent_groups")
