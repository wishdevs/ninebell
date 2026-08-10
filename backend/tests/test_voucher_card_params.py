"""voucher-card 실행 파라미터 — 공유 max_rows + 회계일(accounting_ym) override 정규화."""

from __future__ import annotations

import pytest

from app.agents.voucher_card.params import VoucherCardParams, parse_voucher_card_params


def test_defaults_all_and_this_month():
    p = parse_voucher_card_params({})
    assert isinstance(p, VoucherCardParams)
    assert p.max_rows is None  # 전체
    assert p.accounting_ym is None  # 당월(폼 기본값)


def test_default_when_params_none():
    p = parse_voucher_card_params(None)
    assert p.max_rows is None and p.accounting_ym is None


def test_explicit_max_rows_flat_and_nested():
    assert parse_voucher_card_params({"max_rows": 3}).max_rows == 3
    assert parse_voucher_card_params({"voucher": {"max_rows": 2}}).max_rows == 2


def test_accounting_ym_yyyymm_kept():
    assert parse_voucher_card_params({"accounting_ym": "202607"}).accounting_ym == "202607"


def test_accounting_ym_hyphen_normalized():
    # 'YYYY-MM' → 'YYYYMM' 정규화.
    assert parse_voucher_card_params({"accounting_ym": "2026-07"}).accounting_ym == "202607"


def test_accounting_ym_bad_format_rejected():
    with pytest.raises(ValueError):
        parse_voucher_card_params({"accounting_ym": "2026"})
    with pytest.raises(ValueError):
        parse_voucher_card_params({"accounting_ym": "20260732abc"})


def test_accounting_ym_bad_month_rejected():
    with pytest.raises(ValueError):
        parse_voucher_card_params({"accounting_ym": "202613"})  # 13월
    with pytest.raises(ValueError):
        parse_voucher_card_params({"accounting_ym": "202600"})  # 00월


def test_max_rows_below_one_rejected():
    with pytest.raises(ValueError):
        parse_voucher_card_params({"max_rows": 0})


def test_legacy_keys_ignored():
    p = parse_voucher_card_params({"max_rows": 5, "allow_batch": False, "junk": 1})
    assert p.max_rows == 5 and p.accounting_ym is None
