"""card_seed_selections — 전사 기초자료(가맹점 → 계정·적요) 집계

Revision ID: 0013_card_seed_selections
Revises: 0012_card_learned_selections
Create Date: 2026-07-04

법인카드 3년치 거래 엑셀을 가맹점 단위로 집계한 전사 폴백 tier. user_id 없음(공용),
norm_merchant 유니크. 개인 학습이 없을 때 AI 추천 힌트로 쓰는 최근성 가중 최빈 계정·적요.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_card_seed_selections"
down_revision: str | None = "0012_card_learned_selections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_seed_selections",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("norm_merchant", sa.String(length=255), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=False),
        sa.Column("acct_code", sa.String(length=32), nullable=True),
        sa.Column("acct_name", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dominance", sa.Float(), nullable=False, server_default="1"),
        sa.Column("last_year", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("norm_merchant", name="uq_card_seed_merchant"),
    )


def downgrade() -> None:
    op.drop_table("card_seed_selections")
