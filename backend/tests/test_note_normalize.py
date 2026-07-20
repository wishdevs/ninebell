"""적요 정규화 — 사람이름 제외 + 판/제 구분 동적화(card_learning 순수 헬퍼).

사용자 확정(2026-07-20): 사람이름 든 적요는 추천 금지, 원본의 판/제 구분(-판매/-제품 등)은
떼고 접속자 비용구분(판관비→판매 / 제조원가→제조)으로 재부착(구분 원래 있던 적요만).
"""

import pytest

from app.services.card_learning import (
    apply_cost_suffix,
    is_person_name_note,
    strip_division,
)


@pytest.mark.parametrize(
    "note",
    [
        "박건희, 이재혁 석식",
        "신형근, 양승현, 박건희, 박준서, 윤정수 석식",
        "양원주, 황태연 중식",
        "중국출장 숙박(장일환)",
        "중국출장 숙박(김영일,황성국) 2,688위안",
        "중국출장 숙박(장일환,손용선) 458.19달러",
        "해외출장 부식비(장일환 외 2명)",
        "중국출장 거래처 미팅(장일환) 207위안",
    ],
)
def test_is_person_name_note_positive(note):
    assert is_person_name_note(note) is True


@pytest.mark.parametrize(
    "note",
    [
        "직원 야근식대(법인카드)-제품",
        "직원 야근식대(법인카드)-판매",
        "거래처 접대비 (법인카드)-판매",
        "해외출장 교통비(법인카드)-판매",  # 출장 + (법인카드) — 오검출 금지
        "업무추진비(판매)",
        "중식대금",
        "음료-회의(법인카드)-제품",
        None,
        "",
    ],
)
def test_is_person_name_note_negative(note):
    assert is_person_name_note(note) is False


@pytest.mark.parametrize(
    "note,base,had",
    [
        ("직원 야근식대(법인카드)-제품", "직원 야근식대(법인카드)", True),
        ("직원 야근식대(법인카드)-판매", "직원 야근식대(법인카드)", True),
        ("거래처 접대비 (법인카드)-판매", "거래처 접대비 (법인카드)", True),
        ("업무추진비(판매)", "업무추진비", True),
        ("업무추진비(제품)", "업무추진비", True),
        ("음료-회의(법인카드)-제품", "음료-회의(법인카드)", True),
        ("중식대금", "중식대금", False),
        ("복리후생비-석식", "복리후생비-석식", False),  # -석식 은 구분 아님
    ],
)
def test_strip_division(note, base, had):
    assert strip_division(note) == (base, had)


@pytest.mark.parametrize(
    "note,cost_type,expected",
    [
        ("직원 야근식대(법인카드)-판매", "판관비", "직원 야근식대(법인카드)-판매"),
        ("직원 야근식대(법인카드)-판매", "제조원가", "직원 야근식대(법인카드)-제조"),
        ("직원 야근식대(법인카드)-제품", "판관비", "직원 야근식대(법인카드)-판매"),
        ("업무추진비(판매)", "제조원가", "업무추진비-제조"),
        ("중식대금", "제조원가", "중식대금"),  # 구분 없던 적요 — 접미사 안 붙음
        ("직원 야근식대(법인카드)-판매", None, "직원 야근식대(법인카드)"),  # cost_type 미상 → base
        (None, "판관비", None),
    ],
)
def test_apply_cost_suffix(note, cost_type, expected):
    assert apply_cost_suffix(note, cost_type) == expected
