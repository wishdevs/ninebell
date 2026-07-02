"""add agents.workflow_id + users.org_unit_id (실행 게이트 P1-A)

Revision ID: 0006_agent_workflow_user_org
Revises: 0005_org_units_agent_access
Create Date: 2026-07-02

agents.workflow_id: DB agent id(슬러그) ↔ 실행 레지스트리 워크플로우 id 매핑을 서버로 이관.
  기존 데이터: card-chat → card-collect(유일한 실동작 워크플로우).
users.org_unit_id: 사용자 소속 조직구분(FK org_units, SET NULL). 실행 조직접근 게이트 기준.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_agent_workflow_user_org"
down_revision: str | None = "0005_org_units_agent_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("workflow_id", sa.String(length=64), nullable=True))
    op.create_index("ix_agents_workflow_id", "agents", ["workflow_id"], unique=True)
    op.add_column("users", sa.Column("org_unit_id", sa.String(length=40), nullable=True))
    op.create_index("ix_users_org_unit_id", "users", ["org_unit_id"])
    op.create_foreign_key(
        "fk_users_org_unit_id_org_units",
        "users",
        "org_units",
        ["org_unit_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # 기존 데이터: card-chat 에이전트를 실동작 워크플로우(card-collect)에 매핑.
    op.execute("UPDATE agents SET workflow_id = 'card-collect' WHERE id = 'card-chat'")


def downgrade() -> None:
    op.drop_constraint("fk_users_org_unit_id_org_units", "users", type_="foreignkey")
    op.drop_index("ix_users_org_unit_id", table_name="users")
    op.drop_column("users", "org_unit_id")
    op.drop_index("ix_agents_workflow_id", table_name="agents")
    op.drop_column("agents", "workflow_id")
