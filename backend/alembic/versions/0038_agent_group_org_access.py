"""에이전트 그룹 조직접근 — agent_group_org_access + agent_groups.access_configured/allow_unassigned.

그룹 접근권한(사용자 지시 2026-08-31): 조직구분이 그룹 게이트와 그룹 내 에이전트 게이트를
**둘 다** 통과해야 에이전트가 보인다/실행된다. 에이전트 단위 규칙(0005/0008)과 완전 대칭 —
행 존재 = 허용, access_configured=false(최초) = 전체 허용.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0038_agent_group_org_access"
down_revision: str | None = "0037_purchase_order_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_groups",
        sa.Column("access_configured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agent_groups",
        sa.Column("allow_unassigned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "agent_group_org_access",
        sa.Column(
            "group_id",
            sa.String(length=64),
            sa.ForeignKey("agent_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "org_unit_id",
            sa.String(length=40),
            sa.ForeignKey("org_units.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    # 조직구분 기준 역조회 대비 — agent_org_access 의 ix_* 인덱스와 동일 이유.
    op.create_index(
        "ix_agent_group_org_access_org_unit_id", "agent_group_org_access", ["org_unit_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_group_org_access_org_unit_id", table_name="agent_group_org_access")
    op.drop_table("agent_group_org_access")
    op.drop_column("agent_groups", "allow_unassigned")
    op.drop_column("agent_groups", "access_configured")
