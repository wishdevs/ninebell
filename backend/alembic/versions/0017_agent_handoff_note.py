"""agents.handoff_note — 완료 후 사람이 이어서 할 일(핸드오프 안내)

Revision ID: 0017_agent_handoff_note
Revises: 0016_agent_groups
Create Date: 2026-07-06

에이전트는 자동화 가능한 지점까지만 실행하고, 이후 사람이 이어받아야 하는 업무가 있다
(예: 카드 결의서는 저장까지가 에이전트 몫이고, 저장된 건의 결제(승인) 상신은 사람이 한다).
완료 화면에서 이 안내를 성공 결과와 구분해 보여주기 위한 선언적 필드. 값은 멱등 시드가 채운다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_agent_handoff_note"
down_revision: str | None = "0016_agent_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("handoff_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "handoff_note")
