"""expense_card.domain 단위테스트 — 예산단위/적요 도메인 매핑(page 무관, 순수 함수).

계약 이식원본: ninebell `_BUDGET_MAP`·`_REMARK_MAP`·역추론 규칙.
"""

from __future__ import annotations

from app.agents.expense_card.domain import (
    BUDGET_MAP,
    REMARK_MAP,
    budget_for,
    norm_item,
    remark_for,
    use_item_from_remark,
)


def test_norm_item_strips_space_underscore_hyphen_slash_paren():
    assert norm_item(" 야근 식대 ") == "야근식대"
    assert norm_item("SPARES_ACM") == norm_item("spares acm")
    assert norm_item("복리후생비-석식") == "복리후생비석식"
    assert norm_item("계정(제)") == "계정제"
    assert norm_item(None) == ""


def test_budget_for_verified_and_normalized_match():
    # '야근식대'(석식) — 라이브 검증 항목.
    assert budget_for("야근식대") == ("석식", "복리후생비-석식")
    # 공백/정규화가 달라도 매칭.
    assert budget_for(" 야근 식대 ") == ("석식", "복리후생비-석식")
    assert budget_for("회식") == ("회식", "복리후생비-회식")


def test_budget_for_unknown_returns_none():
    assert budget_for("택시비") is None
    assert budget_for("") is None


def test_remark_for_custom_then_fallback():
    assert remark_for("야근식대") == "직원 야근 식대(법인카드)"
    assert remark_for("회식") == "직원 회식(법인카드)"
    # 커스텀 매핑에 없으면 '{사용항목}(법인카드)' 폴백.
    assert remark_for("중식식대") == "중식식대(법인카드)"
    assert remark_for("사무용품비") == "사무용품비(법인카드)"


def test_use_item_from_remark_reverse_maps():
    # 커스텀 적요 역매핑.
    assert use_item_from_remark("직원 야근 식대(법인카드)") == "야근식대"
    # 기본 패턴 "{사용항목}(법인카드)" — BUDGET_MAP 에 있는 항목만.
    assert use_item_from_remark("중식식대(법인카드)") == "중식식대"
    # BUDGET_MAP 에 없는 접미사 → None.
    assert use_item_from_remark("택시비(법인카드)") is None
    assert use_item_from_remark("") is None
    assert use_item_from_remark("그냥 메모") is None


def test_maps_have_expected_domain_keys():
    # 사용자 제공 규칙의 핵심 항목이 보존됐는지(회귀 방지).
    for k in ("야근식대", "회식", "국내출장", "유류", "접대비", "중식식대"):
        assert k in BUDGET_MAP
    assert REMARK_MAP["주차료"] == "국내출장 주차료(법인카드)"
