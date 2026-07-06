"""agents.settings — 에이전트별 세부설정 저장값(JSON)

Revision ID: 0018_agent_settings
Revises: 0017_agent_handoff_note
Create Date: 2026-07-06

설정 항목의 정의(스키마)는 코드가 단일 소스다(app/services/agent_settings.py —
AGENT_SETTINGS_SCHEMA). DB 에는 관리자가 저장한 값만 담는다. NULL = 저장값 없음
(스키마 기본값 사용). 시드는 이 컬럼을 건드리지 않는다(관리자 값 보존).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_agent_settings"
down_revision: str | None = "0017_agent_handoff_note"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "settings",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "settings")
