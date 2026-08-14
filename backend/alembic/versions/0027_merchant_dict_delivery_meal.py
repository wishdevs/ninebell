"""가맹점 사전 — 배달앱을 식대 계열로 결정적 해석(힌트 → strong).

2026-07-27 사용자 감사: 쿠팡이츠 11건(49·59·138·144·148~153·411)이 **소모품비**로 분류됐다.
원인 두 가지:
  1. 매칭이 규칙 **순서**로 첫 매칭을 반환해, 온라인쇼핑 규칙의 '쿠팡'이 배달앱 규칙의
     '쿠팡이츠'보다 앞이라는 이유만으로 배달 음식이 온라인쇼핑으로 잡혔다
     (코드 수정: match_in 을 '가장 구체적인 키워드 우선'으로 변경).
  2. 배달앱 규칙이 acct=NULL·strong=false(힌트만)라, AI 가 실패하면 폴백이 소모품 계열로 갔다.

이 마이그레이션은 (2)를 고친다 — 배달앱을 **식대 계열 앵커**('복리후생비-중식')로 결정적
해석하게 한다. 조식/중식/석식 슬롯은 거래시각으로 `meal_time.correct_budget` 이 최종 확정하므로
(19~21시 배달 → 석식), 여기 값은 '식대 계열'이라는 표시일 뿐 시간대를 고정하지 않는다.

멱등: 이미 acct 가 설정돼 있으면 건드리지 않는다. downgrade 는 힌트 상태로 되돌린다.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0027_merchant_dict_delivery_meal"
down_revision: str | None = "0026_merchant_dict_electronics"
branch_labels = None
depends_on = None

_MEAL_ANCHOR = "복리후생비-중식"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE merchant_dict_rules SET acct = :acct, strong = true "
            "WHERE keywords LIKE '%쿠팡이츠%' AND (acct IS NULL OR acct = '')"
        ),
        {"acct": _MEAL_ANCHOR},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE merchant_dict_rules SET acct = NULL, strong = false "
            "WHERE keywords LIKE '%쿠팡이츠%' AND acct = :acct"
        ),
        {"acct": _MEAL_ANCHOR},
    )
