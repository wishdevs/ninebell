"""agents.allow_unassigned — 조직구분 미지정 사용자의 에이전트 실행 허용 플래그

Revision ID: 0008_agent_allow_unassigned
Revises: 0007_run_boundaries_indexes
Create Date: 2026-07-02

에이전트 접근 관리에 '미지정' 항목 추가 — access_configured=true 인 에이전트에 대해
org_unit_id 가 NULL 인 사용자의 실행 허용 여부를 명시한다(기본 false = 기존 동작 유지).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_agent_allow_unassigned"
down_revision: str | None = "0007_run_boundaries_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "allow_unassigned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "allow_unassigned")
