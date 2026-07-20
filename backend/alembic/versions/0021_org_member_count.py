"""org_units.member_count — ERP 인원수(서브트리 합계) 컬럼 추가

Revision ID: 0021_org_member_count
Revises: 0020_card_ai_note
Create Date: 2026-07-20

직속 인원 판별용 인원수(서브트리 합계)를 담는다. (member_count - 직속자식합) > 0 이면
그 노드가 직속 인원을 보유 → 배정·비용구분 대상. 순수 컨테이너(본부 등)는 직속 0 → 미배정.
nullable — 기존 행/ERP 미제공 노드는 NULL(백필은 시드·라이브 임포트가 담당).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_org_member_count"
down_revision: str | None = "0020_card_ai_note"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("org_units", sa.Column("member_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("org_units", "member_count")
