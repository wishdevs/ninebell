"""괄호 없는 맨몸 사람이름 적요 3행 정확 교정 — 데이터 전용.

0022·0023 의 규칙(차량번호·이름 괄호·소모품 상세)은 **괄호형** 이름만 다뤘다. 적대 리뷰가
잡은 잔존 3행은 괄호 없이 이름이 본문에 섞인 형태라 정규식 일반화가 위험하다 — 선두
"이름, 이름 …" 나열을 규칙으로 벗기면 "사무용품, 소모품 구매" 같은 정상 적요까지 파괴되는
오검출이 실증됐다. 그래서 **원문 정확 일치 → 교정문** 매핑으로만 고친다(오검출 0 보장).

한계(의도): 향후 유입되는 맨몸 단일 이름(예: "홍길동 야근 후 교통비")은 이 방식으로 못
막는다 — 콤마 나열은 suggest 시점의 is_person_name_note(_NAME_LIST_RE)가 차단하고, 단일
이름은 이름 사전 없이는 판정 불가라 규칙화하지 않는다(card_learning.sanitize_note docstring
의 한계 항목과 동기). 멱등: 교정 후 원문이 사라지므로 재실행 무해. downgrade 는 PII 복원이
되므로 no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0024_fix_bare_name_notes"
down_revision: str | None = "0023_resanitize_card_note_pii"
branch_labels = None
depends_on = None

# 원문 정확 일치 → 교정문 (2026-07-22 dashboard-pg 실측 5행. 이름만 제거, 의미 최소 보존)
_EXACT_FIXES: dict[str, str] = {
    "신형근, 양승현, 박건희, 박준서, 윤정수 석식": "직원 석식",
    "박건희, 이재혁 석식": "직원 석식",
    "박건희 야근 후 교통비": "야근 후 교통비",
    "양승현, 박윤슬, 윤정수 석식": "직원 석식",
    "양원주, 황태연 중식": "직원 중식",
}

_TABLES = ("card_seed_notes", "card_learned_notes", "card_ai_notes")


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        for src, dst in _EXACT_FIXES.items():
            bind.execute(
                sa.text(f"UPDATE {table} SET note = :dst WHERE note = :src"),  # noqa: S608 — 테이블명은 고정 화이트리스트
                {"src": src, "dst": dst},
            )


def downgrade() -> None:
    # PII 를 되살리는 다운그레이드는 하지 않는다 — 의도된 no-op.
    pass
