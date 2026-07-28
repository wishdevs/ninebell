"""가맹점 사전 — 전자·컴퓨터·사무기기 판매 힌트 규칙 추가.

동구전자 등 전자부품·기기 도매/소매는 AI 가 방향(사무용품비)은 맞히나 confidence 가 낮아
(0.3~0.4) 임계값 미달로 폐기→blind 기본값으로 떨어졌다(2026-07-24 실측). 힌트만으로
confidence 0.85 로 올라 채택된다. 계정은 품목 따라 갈려 AI 가 정하도록 힌트만(strong 아님).
멱등: 이미 같은 규칙(키워드 '동구전자' 포함)이 있으면 스킵.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0026_merchant_dict_electronics"
down_revision: str | None = "0025_merchant_dict_rules"
branch_labels = None
depends_on = None

_KEYWORDS = (
    "동구전자,전자상가,전자랜드,용산전자,세운상가,테크노마트,베스트샵,디지털프라자,"
    "컴퓨존,컴퓨터,다나와,아이코다,노트북,오피스디포,문구,복사용지,토너,잉크,사무용품,모나미"
)
_CATEGORY = "전자·컴퓨터·사무기기(소모품/사무용품)"
_SOURCE = "웹+큐레이션"


def upgrade() -> None:
    bind = op.get_bind()
    # 멱등 — 이미 이 규칙(키워드에 '동구전자' 포함)이 있으면 재삽입하지 않는다.
    exists = bind.execute(
        sa.text("SELECT COUNT(*) FROM merchant_dict_rules WHERE keywords LIKE '%동구전자%'")
    ).scalar_one()
    if exists:
        return
    # sort_order 는 기존 최대값 다음(없으면 0).
    max_ord = bind.execute(
        sa.text("SELECT COALESCE(MAX(sort_order), 0) FROM merchant_dict_rules")
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO merchant_dict_rules "
            "(id, keywords, category, acct, strong, source, sort_order, enabled) "
            "VALUES (:id, :kw, :cat, NULL, false, :src, :ord, true)"
        ),
        {
            "id": uuid.uuid4(),
            "kw": _KEYWORDS,
            "cat": _CATEGORY,
            "src": _SOURCE,
            "ord": int(max_ord) + 10,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM merchant_dict_rules WHERE keywords LIKE '%동구전자%'")
    )
