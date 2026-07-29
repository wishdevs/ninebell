"""users.job_title 추가 — 사용자 패널 이름("석대현 프로")에서 분리한 직책.

직책이 이름에 섞여 저장되면 법인카드 본인 카드 매칭(카드명 괄호 "(석대현)")에 순수
이름을 쓸 수 없다. 직책을 별도 컬럼으로 기억하고 display_name 은 순수 이름으로 유지한다.
기존 행은 다음 로그인 시 _apply_profile 이 분리값으로 갱신한다(백필 불필요).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0031_users_job_title"
down_revision: str | None = "0030_changelog_released_at_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("job_title", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "job_title")
