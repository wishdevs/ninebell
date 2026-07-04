"""card_learned_selections — 사용자 개입 학습(가맹점 → 선택) 저장

Revision ID: 0012_card_learned_selections
Revises: 0011_org_units_hierarchy_cost
Create Date: 2026-07-04

card-collect 그리드 개입에서 확정한 선택을 (user_id, norm_merchant) 유니크로 누적한다
(가맹점 단위 — 거래 수가 아니라 서로 다른 가맹점 수로만 성장). 추후 AI 추천 힌트·결정적
프리필에 재사용. users 삭제 시 CASCADE.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_card_learned_selections"
down_revision: str | None = "0011_org_units_hierarchy_cost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_learned_selections",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("norm_merchant", sa.String(length=255), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=False),
        sa.Column("budget", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("project", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "norm_merchant", name="uq_card_learned_user_merchant"),
    )
    op.create_index("ix_card_learned_user", "card_learned_selections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_card_learned_user", table_name="card_learned_selections")
    op.drop_table("card_learned_selections")
