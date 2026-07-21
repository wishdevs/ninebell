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
