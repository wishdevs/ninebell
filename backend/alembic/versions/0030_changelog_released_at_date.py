"""changelog_entries.released_at 을 timestamptz → date 로 정정.

릴리스 날짜는 '시각'이 아니라 '달력 날짜'다. timestamptz 로 두면 KST 자정으로 넣은 값이
UTC 로 저장(2026-07-28 → 2026-07-27T15:00Z)돼, 읽을 때 하루 밀린 날짜가 나오고
수정 다이얼로그가 그 값을 그대로 다시 저장하면서 날짜가 매번 하루씩 뒤로 걸어갔다.

기존 행은 Asia/Seoul 기준으로 환산해 '의도했던 날짜'를 그대로 보존한다.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0030_changelog_released_at_date"
down_revision: str | None = "0029_changelog_has_major_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "changelog_entries",
        "released_at",
        type_=sa.Date(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="(released_at AT TIME ZONE 'Asia/Seoul')::date",
    )


def downgrade() -> None:
    op.alter_column(
        "changelog_entries",
        "released_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.Date(),
        existing_nullable=False,
        postgresql_using="(released_at::timestamp AT TIME ZONE 'Asia/Seoul')",
    )
