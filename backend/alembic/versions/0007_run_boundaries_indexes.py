"""agent_runs.id 40→64 + 조회 인덱스 보강 (P3-2 경계·성능)

Revision ID: 0007_run_boundaries_indexes
Revises: 0006_agent_workflow_user_org
Create Date: 2026-07-02

- agent_runs.id String(40)→64: 클라이언트 런 id 경계 여유.
- ix_agent_runs_user_started(user_id, started_at): 로깅 목록 소유자 스코프 최신순 정렬 스캔 회피.
- ix_agent_org_access_org_unit_id: 조직구분 기준 역조회(PK 선두가 agent_id라 못 타는 경로).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_run_boundaries_indexes"
down_revision: str | None = "0006_agent_workflow_user_org"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "agent_runs",
        "id",
        existing_type=sa.String(length=40),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_index("ix_agent_runs_user_started", "agent_runs", ["user_id", "started_at"])
    op.create_index("ix_agent_org_access_org_unit_id", "agent_org_access", ["org_unit_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_org_access_org_unit_id", table_name="agent_org_access")
    op.drop_index("ix_agent_runs_user_started", table_name="agent_runs")
    op.alter_column(
        "agent_runs",
        "id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=40),
        existing_nullable=False,
    )
