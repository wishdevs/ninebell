"""add local-auth columns to users (password_hash, agreed_terms_at)

Revision ID: 0002_user_local_auth
Revises: 0001_initial
Create Date: 2026-07-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_user_local_auth"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 로컬 계정(시스템 관리자 등) bcrypt 해시. 옴니솔 계정은 null.
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    # 회원가입 약관 동의 시각(가입한 옴니솔 계정). 미가입/미동의는 null.
    op.add_column("users", sa.Column("agreed_terms_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "agreed_terms_at")
    op.drop_column("users", "password_hash")
