"""add is_default to user_code_favorites

Revision ID: 0010_favorite_is_default
Revises: 0009_user_code_favorites_catalog
Create Date: 2026-07-02

사용자별 즐겨찾기 중 (user, kind) 당 1개를 '기본'으로 지정하기 위한 플래그.
단일성(한 kind 당 1개만 true)은 애플리케이션(POST /me/favorites/{id}/default)이 보장한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_favorite_is_default"
down_revision: str | None = "0009_user_code_favorites_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_code_favorites",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_code_favorites", "is_default")
