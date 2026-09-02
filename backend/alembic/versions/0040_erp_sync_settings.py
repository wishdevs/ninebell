"""ERP 동기화 항목별 주기 설정 — erp_sync_settings.

자정 고정 스케줄(v3.10.0)을 항목(kind)별 주기로 바꾼다(사용자 요청 2026-09-02). 행이 없으면
기본값(예산단위·프로젝트·거래처 1시간, ERP 조직 일주일)이라 데이터 이행은 없다.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0040_erp_sync_settings"
down_revision: str | None = "0039_erp_sync_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_sync_settings",
        sa.Column("kind", sa.String(length=32), primary_key=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_by",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("erp_sync_settings")
