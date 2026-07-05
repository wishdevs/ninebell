"""agent_step_phase — 큰 단계(카테고리) 라벨

Revision ID: 0015_agent_step_phase
Revises: 0014_agent_step_intervention
Create Date: 2026-07-05

agent_steps.phase(String(64), nullable) 추가 — UI Phase 아코디언 그룹핑의 소스.
기존 행 값 채움은 멱등 시드(seed_agents)가 처리한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_agent_step_phase"
down_revision: str | None = "0014_agent_step_intervention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_steps",
        sa.Column("phase", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_steps", "phase")
