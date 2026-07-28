"""회계일 조회기간 파라미터(전표 3종 공용) + 조회화면 세팅 스텝 경로 선택 테스트.

핵심 계약 3가지:
  1) 폼 입력('YYYY-MM-DD')이 YYYYMMDD 로 정규화되고, 반쪽/역전 기간은 한국어 오류로 거부된다.
  2) 미지정·당월(1일~말일)은 **프로브로 검증된 setMonth() 경로**를 그대로 탄다(기본 실행 무영향).
  3) 그 외 기간(월 부분 기간 등)만 input 직접 세팅 + readback 확인 — 불일치는 하드 실패.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agents.common.voucher_period import (
    VoucherPeriodParams,
    current_month_range,
    is_current_month_range,
    month_range,
    normalize_ymd,
)
from app.agents.voucher_card.params import parse_voucher_card_params
from app.agents.voucher_receivable import steps
from app.agents.voucher_receivable.params import parse_voucher_params


# ── 정규화·검증 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw", ["2026-07-01", "20260701"])
def test_normalize_accepts_both_forms(raw):
    assert normalize_ymd(raw) == "20260701"


@pytest.mark.parametrize("raw", ["2026-7-1", "20260732", "2026-02-30", "abc", "202607"])
def test_normalize_rejects_bad_dates(raw):
    with pytest.raises(ValueError):
        normalize_ymd(raw)


def test_month_range_handles_month_length():
    assert month_range(2026, 2) == ("20260201", "20260228")
    assert month_range(2026, 7) == ("20260701", "20260731")


def test_current_month_range_uses_today():
    assert current_month_range(date(2026, 7, 28)) == ("20260701", "20260731")
    assert is_current_month_range("20260701", "20260731", date(2026, 7, 28))
    # 월 부분 기간은 '당월 전체'가 아니다 — 별도 경로로 가야 한다.
    assert not is_current_month_range("20260701", "20260705", date(2026, 7, 28))


def test_period_params_empty_is_unset():
    p = VoucherPeriodParams()
    assert (p.period_from, p.period_to) == (None, None)
    assert p.period_label == "당월"


def test_period_params_label_and_normalization():
    p = VoucherPeriodParams(period_from="2026-07-01", period_to="2026-07-05")
    assert (p.period_from, p.period_to) == ("20260701", "20260705")
    assert p.period_label == "2026-07-01 ~ 2026-07-05"


def test_period_params_rejects_half_and_reversed():
    with pytest.raises(ValueError, match="함께 지정"):
        VoucherPeriodParams(period_from="2026-07-01")
    with pytest.raises(ValueError, match="늦을 수 없"):
        VoucherPeriodParams(period_from="2026-07-31", period_to="2026-07-01")


# ── 3종 params 진입점 ──────────────────────────────────────────────────────────
def test_receivable_params_reads_nested_period():
    p = parse_voucher_params({"voucher": {"period_from": "2026-07-01", "period_to": "2026-07-05"}})
    assert (p.period_from, p.period_to) == ("20260701", "20260705")
    assert p.max_rows is None  # 기본 전체 유지


def test_card_params_reads_period():
    p = parse_voucher_card_params({"voucher": {"period_from": "20260701", "period_to": "20260705"}})
    assert (p.period_from, p.period_to) == ("20260701", "20260705")


def test_card_params_legacy_ym_expands_to_month_range():
    """구 accounting_ym('YYYYMM')은 그 월의 1일~말일 기간으로 흡수된다(하위호환)."""
    p = parse_voucher_card_params({"voucher": {"accounting_ym": "2026-02"}})
    assert (p.period_from, p.period_to) == ("20260201", "20260228")


def test_card_params_explicit_period_wins_over_legacy_ym():
    p = parse_voucher_card_params(
        {"voucher": {"accounting_ym": "202602", "period_from": "20260701", "period_to": "20260705"}}
    )
    assert (p.period_from, p.period_to) == ("20260701", "20260705")


def test_card_params_invalid_period_is_korean_error():
    with pytest.raises(ValueError, match="올바르지 않"):
        parse_voucher_card_params({"voucher": {"period_from": "2026-07-01", "period_to": "bad"}})


# ── 조회화면 회계일 세팅 경로 선택 ────────────────────────────────────────────
class _StubPage:
    """page.evaluate(js, arg) 를 기록하는 최소 스텁 — js 상수로 어떤 경로를 탔는지 판별한다."""

    def __init__(self, values=None, range_ok=True):
        self.calls: list[tuple[str, object]] = []
        self._values = values
        self._range_ok = range_ok

    async def evaluate(self, js_src, arg=None):
        from app.agents.voucher_receivable import js as vr_js

        if js_src == vr_js.SET_PERIOD_THIS_MONTH_JS:
            self.calls.append(("month", arg))
            return True
        if js_src == vr_js.SET_PERIOD_RANGE_JS:
            self.calls.append(("range", arg))
            return self._range_ok
        if js_src == vr_js.PERIOD_VALUE_JS:
            self.calls.append(("read", arg))
            return self._values
        raise AssertionError(f"예상치 못한 evaluate 호출: {js_src!r}")


async def test_set_period_unset_uses_month_path():
    page = _StubPage()
    assert (await steps.set_period(page))["ok"]
    assert [c[0] for c in page.calls] == ["month"]


async def test_set_period_current_month_uses_month_path():
    start, end = current_month_range()
    page = _StubPage()
    assert (await steps.set_period(page, start, end))["ok"]
    assert [c[0] for c in page.calls] == ["month"]


async def test_set_period_partial_range_sets_inputs_and_verifies():
    page = _StubPage(values={"start": "20260701", "end": "20260705"})
    r = await steps.set_period(page, "20260701", "20260705")
    assert r["ok"] and r["display"] == "20260701~20260705"
    assert [c[0] for c in page.calls] == ["range", "read"]
    assert page.calls[0][1] == {"start": "20260701", "end": "20260705"}


async def test_set_period_mismatch_readback_hard_fails():
    """반영값이 다르면 실패 — 잘못된 회계일로 엉뚱한 전표를 결재하는 것을 막는다."""
    page = _StubPage(values={"start": "20260701", "end": "20260731"})
    r = await steps.set_period(page, "20260701", "20260705")
    assert not r["ok"] and "반영 불일치" in r["reason"]


async def test_set_period_unreadable_widget_warns_but_passes():
    page = _StubPage(values=None)
    r = await steps.set_period(page, "20260701", "20260705")
    assert r["ok"] and "확인 불가" in r["warn"]


async def test_set_period_range_call_failure_reports():
    page = _StubPage(range_ok=False)
    r = await steps.set_period(page, "20260701", "20260705")
    assert not r["ok"] and "시작/종료 input 미발견" in r["reason"]
