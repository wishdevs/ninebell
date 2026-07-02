"""add org_units + agent_org_access + agents.access_configured

Revision ID: 0005_org_units_agent_access
Revises: 0004_agent_templates
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_org_units_agent_access"
down_revision: str | None = "0004_agent_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 조직구분 기준 데이터(사용자 제공). id 슬러그는 안정 유지.
_SEED_ORG_UNITS: tuple[tuple[str, str], ...] = (
    ("exec", "임원실"),
    ("mgmt", "경영본부"),
    ("sales", "영업본부"),
    ("china", "중국법인"),
    ("fa-lab", "FA연구소"),
    ("mfg", "제조본부"),
    ("imp-lab", "IMP연구소"),
)


def upgrade() -> None:
    op.create_table(
        "org_units",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_units"),
    )
    op.create_table(
        "agent_org_access",
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("org_unit_id", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="fk_agent_org_access_agent_id_agents", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["org_unit_id"],
            ["org_units.id"],
            name="fk_agent_org_access_org_unit_id_org_units",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("agent_id", "org_unit_id", name="pk_agent_org_access"),
    )
    op.create_index("ix_agent_org_access_agent_id", "agent_org_access", ["agent_id"])
    op.add_column(
        "agents",
        sa.Column(
            "access_configured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # 조직구분 시드(멱등하지 않아도 되는 최초 생성 — 재실행은 downgrade 후).
    org_units = sa.table(
        "org_units",
        sa.column("id", sa.String),
        sa.column("label", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        org_units,
        [
            {"id": slug, "label": label, "sort_order": i}
            for i, (slug, label) in enumerate(_SEED_ORG_UNITS)
        ],
    )


def downgrade() -> None:
    op.drop_column("agents", "access_configured")
    op.drop_index("ix_agent_org_access_agent_id", table_name="agent_org_access")
    op.drop_table("agent_org_access")
    op.drop_table("org_units")
