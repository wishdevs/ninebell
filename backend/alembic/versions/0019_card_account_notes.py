"""card_seed_notes / card_learned_notes — (가맹점 × 계정) → 적요 데이터 계층

Revision ID: 0019_card_account_notes
Revises: 0018_agent_settings
Create Date: 2026-07-13

사람이 카드 개입에서 예산단위(=계정)를 바꾸면 그 계정에 맞는 적요를 결정적으로 추천하기 위한
전용 tier. 기존 card_seed_selections / card_learned_selections(가맹점 → 예산단위)와 **별개**로,
계정별 적요만 담는다.

- card_seed_notes(전사): 유니크 (norm_merchant, acct_code) — 3년치 엑셀 집계 폴백.
- card_learned_notes(개인): 유니크 (user_id, norm_merchant, acct_code) — 개입 확정 누적, CASCADE.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_card_account_notes"
down_revision: str | None = "0018_agent_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_seed_notes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("norm_merchant", sa.String(length=255), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=False),
        sa.Column("acct_code", sa.String(length=32), nullable=False),
        sa.Column("acct_name", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dominance", sa.Float(), nullable=False, server_default="1"),
        sa.Column("last_year", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("norm_merchant", "acct_code", name="uq_card_seed_note_merchant_acct"),
    )
    op.create_index("ix_card_seed_note_merchant", "card_seed_notes", ["norm_merchant"])

    op.create_table(
        "card_learned_notes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("norm_merchant", sa.String(length=255), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=False),
        sa.Column("acct_code", sa.String(length=32), nullable=False),
        sa.Column("acct_name", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "norm_merchant", "acct_code", name="uq_card_learned_note_user_merchant_acct"
        ),
    )
    op.create_index("ix_card_learned_note_user", "card_learned_notes", ["user_id"])
    op.create_index("ix_card_learned_note_merchant", "card_learned_notes", ["norm_merchant"])


def downgrade() -> None:
    op.drop_index("ix_card_learned_note_merchant", table_name="card_learned_notes")
    op.drop_index("ix_card_learned_note_user", table_name="card_learned_notes")
    op.drop_table("card_learned_notes")
    op.drop_index("ix_card_seed_note_merchant", table_name="card_seed_notes")
    op.drop_table("card_seed_notes")
