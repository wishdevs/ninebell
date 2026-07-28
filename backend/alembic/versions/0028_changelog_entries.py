"""changelog_entries 테이블 생성 — 릴리스 단위 변경사항(릴리스 노트).

본문은 마크다운(body_md). status='released' 만 전 사용자 공개, 'draft' 는 관리자 전용.
released_at 이 목록 정렬(최신순) 기준이라 인덱스를 건다. version 은 중복 불가.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0028_changelog_entries"
down_revision: str | None = "0027_merchant_dict_delivery_meal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "changelog_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="released"),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("version", name="uq_changelog_entries_version"),
    )
    op.create_index("ix_changelog_entries_released_at", "changelog_entries", ["released_at"])


def downgrade() -> None:
    op.drop_index("ix_changelog_entries_released_at", table_name="changelog_entries")
    op.drop_table("changelog_entries")
