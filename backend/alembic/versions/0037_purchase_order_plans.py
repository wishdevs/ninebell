"""purchase_order_plans 테이블 생성 — 구매발주 계획서 확정본 보관.

계획서 HITL 에서 검증 통과한 계획(JSON)과 목록용 파생 컬럼(프로젝트·WBS·발주단위 수·합계)을
저장한다. run_id 는 FK 없는 느슨한 연결. 목록은 (user_id, created_at) 최신순.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0037_purchase_order_plans"
down_revision: str | None = "0036_merge_voucher_by_type_agent"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "purchase_order_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("project_code", sa.String(64), nullable=True),
        sa.Column("project_name", sa.String(200), nullable=True),
        sa.Column("wbs", sa.String(64), nullable=True),
        sa.Column("unit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("plan", _JSON, nullable=False),
        sa.Column("bom_summary", _JSON, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_purchase_order_plans_user_id", "purchase_order_plans", ["user_id"])
    op.create_index("ix_purchase_order_plans_run_id", "purchase_order_plans", ["run_id"])
    op.create_index(
        "ix_purchase_order_plans_user_created", "purchase_order_plans", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_order_plans_user_created", table_name="purchase_order_plans")
    op.drop_index("ix_purchase_order_plans_run_id", table_name="purchase_order_plans")
    op.drop_index("ix_purchase_order_plans_user_id", table_name="purchase_order_plans")
    op.drop_table("purchase_order_plans")
