"""card_collect.grouping — 그룹 판단 계획(대표 선정·금액 이탈·취소 미러) 순수 함수 단위 테스트."""

from __future__ import annotations

from app.agents.card_collect import grouping


def _row(merchant="맘스터치 상대원점", amt="9000", tm="18:30:00", yn="승인", no=""):
    return {"TRAN_NM": merchant, "TRAN_AMT": amt, "TRAN_TM": tm, "APRVL_YN": yn, "APRVL_NO": no}


# ── parse_amount / is_cancel / group_slot ─────────────────────────────────────
def test_parse_amount_handles_commas_and_negatives():
    assert grouping.parse_amount("99,950") == 99_950
    assert grouping.parse_amount("-13,600") == -13_600
    assert grouping.parse_amount("") is None
    assert grouping.parse_amount("금액오류") is None


def test_is_cancel_by_label_or_negative_amount():
    assert grouping.is_cancel(_row(yn="승인취소"))
    assert grouping.is_cancel(_row(amt="-10,500"))  # 라벨 누락 시 음수 폴백
    assert not grouping.is_cancel(_row())


def test_group_slot_unknown_for_zero_time():
    """00:00 은 자정 결제가 아니라 시각 미전달 — 조식으로 묶으면 안 된다."""
    assert grouping.group_slot("00:00:00") == "?"
    assert grouping.group_slot(None) == "?"
    assert grouping.group_slot("08:10:06") == "조식"
    # 중식 폐지(2026-08-13) — 점심도 석식 슬롯이다.
    assert grouping.group_slot("12:30:00") == "석식"
    assert grouping.group_slot("18:30:00") == "석식"


def test_group_key_splits_same_merchant_by_slot():
    """시간대로 계정이 갈리면 슬롯을 나눈다 — 중식 폐지 후 남은 갈림은 조식 ↔ 석식이다."""
    breakfast = grouping.group_key(_row("김치도가 상대원점", tm="08:10:06"))
    dinner = grouping.group_key(_row("김치도가 상대원점", tm="18:50:03"))
    assert breakfast[0] == dinner[0]
    assert breakfast != dinner


def test_group_key_merges_lunch_and_dinner_after_lunch_slot_retired():
    """⚠ 규정 변경(2026-08-13): 점심·저녁이 같은 석식 계정이 되어 **한 그룹**으로 묶인다
    (종전엔 중식/석식으로 갈려 대표행 AI 판단이 두 번 돌았다)."""
    lunch = grouping.group_key(_row("김치도가 상대원점", tm="11:53:15"))
    dinner = grouping.group_key(_row("김치도가 상대원점", tm="18:50:03"))
    assert lunch == dinner


# ── 취소 미러 매칭 ────────────────────────────────────────────────────────────
def test_match_cancel_pairs_by_aprvl_no():
    """승인/취소 쌍은 같은 APRVL_NO — 번호+가맹점으로 원거래를 찾는다."""
    rows = [
        _row("시외버스 모바일 승차권", "13,600", "12:58:55", no="A1"),
        _row("시외버스 모바일 승차권", "-13,600", "12:58:55", yn="승인취소", no="A1"),
    ]
    assert grouping.match_cancel_pairs(rows) == {1: 0}


def test_match_cancel_pairs_falls_back_to_amount_and_skips_unmatched():
    rows = [
        _row("네이버페이", "29,400", "10:00:00"),  # APRVL_NO 없음 → (가맹점,|금액|) 폴백
        _row("네이버페이", "-29,400", "10:00:00", yn="승인취소"),
        _row("트립닷컴", "-347,800", "21:42:32", yn="승인취소"),  # 원거래 없음 → 미매칭
    ]
    pairs = grouping.match_cancel_pairs(rows)
    assert pairs == {1: 0}


def test_match_cancel_pairs_does_not_reuse_original():
    """취소 2건이 같은 원거래 하나에 중복 매칭되면 안 된다(1:1)."""
    rows = [
        _row("네이버페이", "20,280", no="B1"),
        _row("네이버페이", "-20,280", yn="승인취소", no="B1"),
        _row("네이버페이", "-20,280", yn="승인취소", no="B1"),
    ]
    pairs = grouping.match_cancel_pairs(rows)
    assert pairs == {1: 0}  # 두 번째 취소는 원거래 소진 → 미매칭


# ── 그룹 계획(plan_groups) ────────────────────────────────────────────────────
def test_plan_groups_one_representative_per_group():
    """같은 (가맹점×슬롯) 반복 결제는 대표 1행만 AI — 나머지는 전파를 받는다."""
    rows = [_row(amt=a, tm=t) for a, t in [("9,000", "18:10:00"), ("9,900", "18:30:00"), ("10,000", "19:00:00")]]
    plan = grouping.plan_groups(rows)
    assert len(plan.ai_rows) == 1
    rep = plan.ai_rows[0]
    assert rep == 1  # 중앙값(9,900) 근접 행이 대표
    assert plan.propagate == {0: rep, 2: rep}
    assert not plan.outliers and not plan.mirrors


def test_plan_groups_amount_outlier_goes_individual():
    """그룹 금액대를 크게 벗어난 행(회식/접대 가능성)은 전파에서 빠지고 개별 AI 로 간다."""
    rows = [
        _row(amt="9,000"), _row(amt="9,900"), _row(amt="10,000"),
        _row(amt="150,000"),  # 중앙값 ~9,950 의 3배·5만원 하한 모두 초과 → 이탈
    ]
    plan = grouping.plan_groups(rows)
    assert plan.outliers == {3}
    assert 3 in plan.ai_rows  # 개별 판단
    assert 3 not in plan.propagate  # 전파 안 받음
    assert set(plan.propagate.values()) <= set(plan.ai_rows)


def test_plan_groups_team_sized_dinner_is_not_outlier():
    """여러 명 결제(~5만원)는 정상 범위 — 절대 하한(5만원) 이하는 이탈이 아니다."""
    rows = [_row(amt=a) for a in ("9,000", "10,000", "9,500", "48,870")]
    plan = grouping.plan_groups(rows)
    assert not plan.outliers


def test_plan_groups_small_group_never_flags_outlier():
    """표본 3행 미만이면 중앙값을 신뢰할 수 없다 — 이탈 판정 안 함."""
    rows = [_row(amt="9,000"), _row(amt="150,000")]
    plan = grouping.plan_groups(rows)
    assert not plan.outliers


def test_plan_groups_skip_ai_excludes_learned_rows():
    """learned 결정적 행은 AI 대상에서 빠진다. 전원 learned 그룹은 대표도 없다."""
    rows = [_row(amt="9,000"), _row(amt="9,900"), _row(amt="10,000")]
    plan = grouping.plan_groups(rows, skip_ai={0, 1, 2})
    assert plan.ai_rows == [] and plan.propagate == {}


def test_plan_groups_learned_outlier_still_goes_to_ai():
    """learned 가맹점이라도 금액 이탈 행은 개별 AI 로 승격된다(반복 확정 ≠ 이탈 근거)."""
    rows = [_row(amt="9,000"), _row(amt="9,900"), _row(amt="10,000"), _row(amt="200,000")]
    plan = grouping.plan_groups(rows, skip_ai={0, 1, 2, 3})
    assert plan.outliers == {3}
    assert plan.ai_rows == [3]


def test_plan_groups_mirror_rows_excluded_from_groups():
    rows = [
        _row("네이버페이", "29,400", no="C1"),
        _row("네이버페이", "-29,400", yn="승인취소", no="C1"),
    ]
    plan = grouping.plan_groups(rows)
    assert plan.mirrors == {1: 0}
    assert 1 not in plan.ai_rows and 1 not in plan.propagate


def test_plan_groups_unnamed_merchants_not_grouped_together():
    """가맹점명 없는 행들이 한 그룹으로 묶여 서로 전파받으면 안 된다."""
    rows = [_row(merchant="", amt="9,000"), _row(merchant="", amt="9,500")]
    plan = grouping.plan_groups(rows)
    assert len(plan.ai_rows) == 2 and plan.propagate == {}
