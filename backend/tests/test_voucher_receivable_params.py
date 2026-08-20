"""voucher-receivable 실행 파라미터 — 정규화(전체 진행 기본).

- 기본값: max_rows=None(전체, 사용자 결정 2026-07-21). 게이트/allow_batch 없음.
- max_rows 를 명시하면 그 수만큼(양수). 0 이하는 거부. 중첩(params["voucher"]) / flat 둘 다 수용.
- 구 allow_batch 등 다른 키는 무시된다.
"""

from __future__ import annotations

import pytest

from app.agents.voucher_receivable.params import VoucherReceivableParams, parse_voucher_params


def test_default_is_all():
    p = parse_voucher_params({})
    assert isinstance(p, VoucherReceivableParams)
    assert p.max_rows is None  # 전체


def test_default_when_params_none():
    assert parse_voucher_params(None).max_rows is None


def test_explicit_max_rows_flat():
    p = parse_voucher_params({"max_rows": 3})
    assert p.max_rows == 3


def test_explicit_max_rows_nested():
    p = parse_voucher_params({"voucher": {"max_rows": 2}})
    assert p.max_rows == 2


def test_large_explicit_max_rows_allowed():
    # 상한 게이트 없음 — 큰 값도 허용(루프가 rowcount 로 자연 상한).
    assert parse_voucher_params({"max_rows": 100}).max_rows == 100


def test_max_rows_below_one_rejected():
    with pytest.raises(ValueError):
        parse_voucher_params({"max_rows": 0})
    with pytest.raises(ValueError):
        parse_voucher_params({"max_rows": -2})


def test_legacy_allow_batch_key_ignored():
    # 구 allow_batch 플래그를 넘겨도 무시되고 max_rows 만 반영(게이트 제거).
    p = parse_voucher_params({"max_rows": 5, "allow_batch": False})
    assert p.max_rows == 5


# ── 전표유형/메뉴 필터(2026-08-20 유형별 병합) ──────────────────────────────────
def test_docu_types_default_none():
    # 미지정 = None → 그래프 빌드 기본값(전체 3종) 사용.
    assert parse_voucher_params({}).docu_types is None
    assert parse_voucher_params({}).menu_filters is None


def test_docu_types_accepted_and_order_kept():
    p = parse_voucher_params({"voucher": {"docu_types": ["해외매출", "국내매출"]}})
    assert p.docu_types == ["해외매출", "국내매출"]  # 순서 유지.


def test_docu_types_dedup_keeps_first_order():
    p = parse_voucher_params({"voucher": {"docu_types": ["국내매출", "국내매출", "내수구매"]}})
    assert p.docu_types == ["국내매출", "내수구매"]


def test_docu_types_unknown_label_rejected():
    with pytest.raises(ValueError):
        parse_voucher_params({"voucher": {"docu_types": ["일반"]}})


def test_docu_types_empty_list_rejected():
    # 존재하는데 빈 목록 = 선택 0건 실행 사고 방지(미지정과 구분해 거부).
    with pytest.raises(ValueError):
        parse_voucher_params({"voucher": {"docu_types": []}})


def test_docu_types_non_list_rejected():
    with pytest.raises(ValueError):
        parse_voucher_params({"voucher": {"docu_types": "국내매출"}})


def test_menu_filters_stripped_and_deduped():
    p = parse_voucher_params({"voucher": {"menu_filters": [" 매출등록 ", "매출취소", "매출등록"]}})
    assert p.menu_filters == ["매출등록", "매출취소"]


def test_menu_filters_empty_list_means_no_filter():
    # 계약: absent OR empty → 미필터(None 정규화).
    assert parse_voucher_params({"voucher": {"menu_filters": []}}).menu_filters is None


def test_menu_filters_blank_item_rejected():
    with pytest.raises(ValueError):
        parse_voucher_params({"voucher": {"menu_filters": ["매출등록", "  "]}})


def test_menu_filters_over_20_rejected():
    with pytest.raises(ValueError):
        parse_voucher_params({"voucher": {"menu_filters": [f"메뉴{i}" for i in range(21)]}})


def test_debug_flag_parsed_from_top_level_only():
    # 디버그 모드(2026-08-10): runs.py 가 **최상위** params["debug"] 로 정규화해 주입한다 —
    # 중첩(voucher) dict 가 있어도 최상위에서 읽어야 한다. True 판정은 정확히 is True.
    from app.agents.voucher_receivable.params import parse_voucher_params

    assert parse_voucher_params({"voucher": {"max_rows": 1}, "debug": True}).debug is True
    assert parse_voucher_params({"debug": True}).debug is True
    assert parse_voucher_params({}).debug is False
    assert parse_voucher_params(None).debug is False
    assert parse_voucher_params({"debug": "yes"}).debug is False  # 문자열은 미해당.
