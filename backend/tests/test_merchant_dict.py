"""가맹점 분류 사전(하이브리드) — app.agents.card_collect.merchant_dict.

카드 표기명(브랜드명과 다름 — PG접두·법인명·지점명·외화접두)에서 업종을 키워드 부분일치로
인식한다. strong=계정 결정적 해석(주유소·해외 OTA), 그 외=AI 힌트.
"""

from __future__ import annotations

from app.agents.card_collect.merchant_dict import DEFAULT_RULES, match_merchant


def test_strong_fuel_various_card_names():
    # 주유소는 카드 표기 변형이 많다 — 전부 차량유지비-유류(strong).
    for name in [
        "(주)삼표에너지야탑주유소",
        "현대오일뱅크(주)직 서현셀프",
        "지에스칼텍스 판교",
        "SK에너지(주) 스타팅광동",
        "남선석유(주)구도일주유소 해성",
    ]:
        r = match_merchant(name)
        assert r is not None and r.acct == "차량유지비-유류" and r.strong is True, name


def test_strong_overseas_ota():
    for name in ["Agoda_아고다_나이스", "Booking.com Amsterdam", "트립닷컴_트립닷컴_이니시스", "Expedia"]:
        r = match_merchant(name)
        assert r is not None and r.acct == "여비교통비-해외출장" and r.strong is True, name


def test_weak_hints_no_account():
    # 애매 업종은 힌트만(acct=None, strong=False) — 카페·택시·편의점·온라인쇼핑.
    for name, cat_kw in [
        ("ALP*DIDI Taxi", "택시"),
        ("(주)스타벅스커피코리아", "카페"),
        ("지에스25 성남센트럴", "편의점"),
        ("쿠팡_쿠팡전용_KCP", "온라인"),
        ("대한항공", "항공"),
    ]:
        r = match_merchant(name)
        assert r is not None and r.acct is None and r.strong is False, name
        assert cat_kw in r.category, (name, r.category)


def test_toll_and_post():
    assert "통행료" in match_merchant("한국도로공사").category
    assert match_merchant("하이플러스카드 주식회사") is not None
    assert match_merchant("우정사업본부(우체국)") is not None


def test_parking_matches_but_not_park_noise():
    # 주차·파킹·주차료는 매칭. '파크' 노이즈(테크노파크·비발디파크)는 오검출 금지.
    for name in ["아이파킹", "하이파킹", "(주)파킹클라우드", "용수주차장", "sk 쉴더스_주차료"]:
        r = match_merchant(name)
        assert r is not None and "주차" in r.category, name
    for noise in ["성남테크노파크", "비발디파크", "성남파크빌"]:
        assert match_merchant(noise) is None, noise


def test_electronics_office_hint():
    # 동구전자 등 전자·컴퓨터·사무기기 판매는 힌트(acct=None, strong=False)로 인식 —
    # AI 가 사무용품비/소모품 방향을 저confidence 로 내던 것을 채택 임계값 위로 끌어올린다.
    for name in [
        "주식회사동구전자_인터넷상거래_",
        "용산전자상가",
        "세운상가 테크노마트",
        "컴퓨존_이니시스",
        "오피스디포 코리아",
        "모나미문구",
    ]:
        r = match_merchant(name)
        assert r is not None and r.acct is None and r.strong is False, name
        assert "전자·컴퓨터" in r.category, (name, r.category)


def test_electronics_rule_no_false_positive_on_전자승차권():
    # ⚠ 바 '전자'를 키워드로 쓰지 않으므로 '전자승차권'(버스표)은 전자 규칙에 안 걸리고
    # 대중교통(시외버스)으로 잡혀야 한다(오탐 회귀).
    r = match_merchant("시외버스 모바일 전자승차권")
    assert r is not None and r.category == "대중교통", r


def test_no_match_returns_none():
    assert match_merchant("알수없는듣보가게 XYZ") is None
    assert match_merchant("") is None
    assert match_merchant(None) is None


def test_keywords_lowercased_for_matching():
    # 규칙 키워드는 소문자여야 부분일치가 성립(match 는 merchant 를 lower 로 비교).
    for rule in DEFAULT_RULES:
        for kw in rule.keywords:
            assert kw == kw.lower(), (rule.category, kw)


def test_match_is_case_insensitive():
    assert match_merchant("AGODA.COM") is not None
    assert match_merchant("agoda") is not None
