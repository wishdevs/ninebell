"""가맹점명 휴리스틱 적요(recommend_note) — 법인 접미 오매칭 방지 회귀.

⚠ '주식회사'의 '식'이 식대 키워드에 걸려 모든 법인 가맹점이 '식대'로 오분류되던 버그
(2026-07-24 동구전자 실측: draft 적요 오염 → AI 계정까지 복리후생비-음료로 오도) 회귀 가드.
"""

from __future__ import annotations

from app.agents.card_collect.nodes._shared import recommend_note


def test_corporate_suffix_does_not_trigger_meal():
    # 주식회사/(주)/㈜ 의 '식'이 식대로 오매칭되면 안 된다 — 일반 '...사용' 이어야 한다.
    for m in ["주식회사동구전자_인터넷상거래_", "(주)삼성물산", "㈜기산시스템", "주식회사 대상"]:
        note = recommend_note(m, amount="")
        assert "식대" not in note, (m, note)
        assert note.endswith("사용"), (m, note)


def test_real_food_merchants_still_meal():
    for m in ["김밥천국", "명동교자식당", "본죽 분식", "굽네치킨", "도미노피자"]:
        assert recommend_note(m, amount="") == "식대(법인카드)", m


def test_other_categories_unaffected():
    assert recommend_note("GS칼텍스 판교주유소", "") == "차량 주유비(법인카드)"
    assert recommend_note("아이파킹 주차장", "") == "주차료(법인카드)"
    assert recommend_note("카카오T 택시", "") == "교통비(법인카드)"
    assert recommend_note("쿠팡", "") == "소모품 구입(법인카드)"


def test_unmatched_returns_generic():
    assert recommend_note("알수없는가게XYZ", "") == "알수없는가게XYZ 사용"
    assert recommend_note("", "") == "법인카드 사용"
