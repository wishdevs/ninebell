"""card_ai_notes — (가맹점 × 계정) → AI 생성 적요 캐시

Revision ID: 0020_card_ai_note
Revises: 0019_card_account_notes
Create Date: 2026-07-14

학습(개인)·seed(전사)에 없는 (가맹점 × 계정) 조합에서만 Gemini 로 계정 맞춤 적요를 1회
생성해 캐시한다. 유니크 (norm_merchant, acct_code) — 전사 공유(사용자별 아님). LLM 재호출을
막는 캐시라 count/dominance 없이 note+model+생성시각만 담는다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_card_ai_note"
down_revision: str | None = "0019_card_account_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_ai_notes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("norm_merchant", sa.String(length=255), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=False),
        sa.Column("acct_code", sa.String(length=32), nullable=False),
        sa.Column("acct_name", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("norm_merchant", "acct_code", name="uq_card_ai_note_merchant_acct"),
    )
    op.create_index("ix_card_ai_note_merchant", "card_ai_notes", ["norm_merchant"])


def downgrade() -> None:
    op.drop_index("ix_card_ai_note_merchant", table_name="card_ai_notes")
    op.drop_table("card_ai_notes")
