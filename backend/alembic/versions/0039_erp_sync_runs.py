"""ERP 동기화 실행 이력 — erp_sync_runs.

관리자 'ERP 동기화' 화면(2026-09-02): 카탈로그 4종(예산단위·프로젝트·거래처·ERP 조직)의 수동·
스케줄 동기화 1회 = 1행. 이전에는 마지막 동기화 시각만 erp_code_catalog.synced_at 으로 영속이고
실패·건너뜀·조직 반영 요약은 RAM 에만 있어 재기동 시 소실됐다.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0039_erp_sync_runs"
down_revision: str | None = "0038_agent_group_org_access"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "erp_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "actor_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("extra", _JSON, nullable=True),
    )
    op.create_index("ix_erp_sync_runs_kind", "erp_sync_runs", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_erp_sync_runs_kind", table_name="erp_sync_runs")
    op.drop_table("erp_sync_runs")
