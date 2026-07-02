"""add user_code_favorites + erp_code_catalog

Revision ID: 0009_user_code_favorites_catalog
Revises: 0008_agent_allow_unassigned
Create Date: 2026-07-02

사용자별 즐겨찾는 ERP 코드(예산단위/프로젝트) + 헤드리스 동기화로 채우는 공용 코드 카탈로그.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_user_code_favorites_catalog"
down_revision: str | None = "0008_agent_allow_unassigned"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_code_favorites",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("extra", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_code_favorites_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_code_favorites"),
        sa.UniqueConstraint("user_id", "kind", "code", name="uq_user_code_favorites_user_id"),
    )
    op.create_index(
        "ix_user_code_favorites_user_id_kind", "user_code_favorites", ["user_id", "kind"]
    )
    op.create_table(
        "erp_code_catalog",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("dept", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("extra", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("kind", "dept", "code", name="pk_erp_code_catalog"),
    )


def downgrade() -> None:
    op.drop_table("erp_code_catalog")
    op.drop_index("ix_user_code_favorites_user_id_kind", table_name="user_code_favorites")
    op.drop_table("user_code_favorites")
