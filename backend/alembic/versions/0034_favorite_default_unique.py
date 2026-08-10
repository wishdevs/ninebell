"""user_code_favorites 기본지정 부분 유니크 — (user_id, kind) WHERE is_default 1행 강제.

Revision ID: 0034_favorite_default_unique
Revises: 0033_run_indexes_integrity_checks
Create Date: 2026-07-31

0033 에서 보류됐던 인덱스의 도입 — 철회 사유였던 me_codes.set_default_favorite 의 한 플러시
커밋(SQLAlchemy UOW 가 UPDATE 를 uuid PK 정렬로 방출해 대상 지정이 형제 해제보다 먼저
나가면 즉시 유니크 위반)은 라우터에 형제 해제 루프 직후 flush 를 선행시켜 해소됐다.

- dedupe: (user_id, kind) 에 is_default=true 가 2행 이상이면 created_at 최신 1행만 유지,
  나머지는 false 로 정정한다(동시각 타이는 id 내림차순으로 결정적 선택).
- 인덱스: uq_user_code_favorites_default(user_id, kind) WHERE is_default — 부분 유니크.
  모델 __table_args__ 에 동일 정의(sqlite_where 병기)가 반영돼 테스트 sqlite create_all
  경로에도 같은 불변식이 걸린다(운영 마이그레이션 대상은 PG 뿐, alembic 미적용).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_favorite_default_unique"
down_revision: str | None = "0033_run_integrity_checks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── ① 기존 위반 데이터 dedupe — (user_id, kind)당 created_at 최신 1행만 기본 유지 ──
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY user_id, kind
                       ORDER BY created_at DESC, id DESC
                   ) AS rn
            FROM user_code_favorites
            WHERE is_default
        )
        UPDATE user_code_favorites
        SET is_default = false
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    # ── ② 부분 유니크 인덱스 — (user_id, kind)당 is_default=true 는 1행뿐 ──────────
    op.create_index(
        "uq_user_code_favorites_default",
        "user_code_favorites",
        ["user_id", "kind"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_code_favorites_default", table_name="user_code_favorites")
