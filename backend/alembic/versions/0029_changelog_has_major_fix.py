"""changelog_entries.has_major_fix 추가 — '주요 수정 포함' 배지·필터용.

잘못 저장·미저장·실행 불가·개인정보 등 반드시 확인해야 할 수정이 포함된 릴리스를
목록에서 배지로 표시하고 필터링하기 위한 유일한 구조화 분류 필드.
나머지 분류(추가/개선/수정/변경/보안)는 본문 마크다운 섹션으로 표현한다.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0029_changelog_has_major_fix"
down_revision: str | None = "0028_changelog_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "changelog_entries",
        sa.Column("has_major_fix", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("changelog_entries", "has_major_fix")
