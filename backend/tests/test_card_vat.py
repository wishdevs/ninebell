"""부가세구분(과세/불공) 분류 — app.agents.card_collect.vat.

과세 거래라도 불공 계정(복리후생비-업무·여비교통비-해외출장·차량유지비-유류·접대비류)이거나
AI 가맹점 판정이 불공이면 '불공'. VAT_TP 가 '과세'가 아니면(빈칸·간이미발급) 불공. 그 외 과세.
"""

from __future__ import annotations

from app.agents.card_collect.vat import (
    NONDEDUCTIBLE,
    TAXABLE,
    classify_vat,
    is_nondeductible_account,
)


def test_taxable_normal_account():
    assert classify_vat("과세", "(판)복리후생비-석식") == TAXABLE


def test_nondeductible_by_account_various_prefixes():
    # (판)/(제) 접두·하이픈 무시하고 불공 계정 매칭.
    assert classify_vat("과세", "(제)복리후생비-업무") == NONDEDUCTIBLE
    assert classify_vat("과세", "(판)여비교통비-해외출장") == NONDEDUCTIBLE
    assert classify_vat("과세", "차량유지비-유류") == NONDEDUCTIBLE
    assert classify_vat("과세", "(판)접대비-국내") == NONDEDUCTIBLE
    assert classify_vat("과세", "접대비") == NONDEDUCTIBLE
    # 접대비 계열은 어순·형태 무관 부분일치 — 해외접대비/국내접대비도 불공.
    assert classify_vat("과세", "(판)해외접대비") == NONDEDUCTIBLE
    assert classify_vat("과세", "국내접대비") == NONDEDUCTIBLE


def test_nondeductible_by_ai_merchant():
    # 계정은 과세 계정이지만 AI(가맹점: 통행료/우체국)가 불공으로 판정 → 불공.
    assert classify_vat("과세", "(판)소모품비", ai_vat="불공") == NONDEDUCTIBLE


def test_ai_taxable_does_not_override():
    assert classify_vat("과세", "(판)소모품비", ai_vat="과세") == TAXABLE
    assert classify_vat("과세", "(판)소모품비", ai_vat=None) == TAXABLE


def test_non_taxable_vat_tp_is_nondeductible():
    # 빈칸·간이미발급 등 비과세 → 기존 2패스 규칙대로 불공.
    assert classify_vat("", "(판)소모품비") == NONDEDUCTIBLE
    assert classify_vat("간이미발급", "(판)소모품비") == NONDEDUCTIBLE


def test_account_beats_ai_and_vat_tp():
    # 계정 불공이 최우선 — VAT_TP 과세여도, AI 과세여도 불공.
    assert classify_vat("과세", "(판)차량유지비-유류", ai_vat="과세") == NONDEDUCTIBLE


def test_is_nondeductible_account():
    assert is_nondeductible_account("(판)접대비-해외") is True
    assert is_nondeductible_account("(판)해외접대비") is True  # 어순 달라도 접대비 부분일치.
    assert is_nondeductible_account("복리후생비-업무") is True
    assert is_nondeductible_account("(판)복리후생비-석식") is False
    assert is_nondeductible_account("") is False
    assert is_nondeductible_account(None) is False
