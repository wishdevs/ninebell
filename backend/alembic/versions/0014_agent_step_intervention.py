"""agent_step_intervention — 단계별 사용자 개입(HITL) 플래그

Revision ID: 0014_agent_step_intervention
Revises: 0013_card_seed_selections
Create Date: 2026-07-05

agent_steps.intervention(bool, 기본 false) 추가 — UI '개입 필요' 배지의 단일 소스.
기존 행 값 갱신(스킬 키 전환 포함)은 멱등 시드(seed_agents)가 처리한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_agent_step_intervention"
down_revision: str | None = "0013_card_seed_selections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_steps",
        sa.Column("intervention", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agent_steps", "intervention")
