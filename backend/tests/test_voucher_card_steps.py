"""voucher-card 스텝 프리미티브 — 프로브 이식 로직의 순수 단위 검증(브라우저 없이).

- read_payment_map: ABDOCU_NO·GWDOCU_NO 둘 다 있는 행만 맵에 담는다 / 그리드 미로딩 우아한 실패.
- set_collect_period: None=미조작(당월 폼 기본) / YYYYMM=그 월 1일~말일 range 세팅.
- run_collect_query: 가시 조회버튼 좌표 클릭.
- Phase C: fill_refdoc_docno(키보드 클리어+타이핑·readback 재시도) / move_refdoc_down(폴백 좌표)
  / click_refdoc_confirm / select_refdoc_row / close_refdoc_dialog.
"""

from __future__ import annotations

import pytest

from app.agents.voucher_card import js as cjs
from app.agents.voucher_card import steps as csteps

pytestmark = pytest.mark.asyncio


class _FakeMouse:
    def __init__(self, sink: list) -> None:
        self._sink = sink

    async def click(self, x, y):
        self._sink.append((x, y))


class _FakePage:
    def __init__(self, responses: dict) -> None:
        self._responses = responses
        self.clicks: list = []
        self.eval_args: dict = {}
        self.mouse = _FakeMouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        self.eval_args[js_src] = arg
        val = self._responses.get(js_src)
        return val(arg) if callable(val) else val

    async def wait_for_timeout(self, ms):
        return None


# ── read_payment_map ──────────────────────────────────────────────────────────
async def test_read_payment_map_filters_rows_missing_fields():
    rows = [
        {"ABDOCU_NO": "RN1", "GWDOCU_NO": "GW1"},
        {"ABDOCU_NO": "RN2", "GWDOCU_NO": None},  # GWDOCU_NO 없음 → 제외
        {"ABDOCU_NO": None, "GWDOCU_NO": "GW3"},  # ABDOCU_NO 없음 → 제외
        {"ABDOCU_NO": "RN4", "GWDOCU_NO": "GW4"},
    ]
    page = _FakePage({cjs.VISIBLE_MASTER_ROWS_JS: {"ok": True, "n": 4, "rows": rows}})
    res = await csteps.read_payment_map(page)
    assert res["ok"] is True
    assert res["map"] == {"RN1": "GW1", "RN4": "GW4"}


async def test_read_payment_map_grid_not_ready_graceful():
    page = _FakePage({cjs.VISIBLE_MASTER_ROWS_JS: {"ok": False, "reason": "grid-not-ready"}})
    res = await csteps.read_payment_map(page)
    assert res["ok"] is False and res["map"] == {} and res["reason"] == "grid-not-ready"


# ── set_collect_period ────────────────────────────────────────────────────────
async def test_set_collect_period_none_is_noop_true():
    page = _FakePage({})  # SET_PERIOD_RANGE_JS 를 호출하지 않아야 한다.
    ok = await csteps.set_collect_period(page, None)
    assert ok is True
    assert cjs.SET_PERIOD_RANGE_JS not in page.eval_args  # 미조작(폼 기본값 당월).


async def test_set_collect_period_override_sets_month_range():
    page = _FakePage({cjs.SET_PERIOD_RANGE_JS: True})
    ok = await csteps.set_collect_period(page, "202602")  # 2026-02(윤년 아님 → 28일)
    assert ok is True
    assert page.eval_args[cjs.SET_PERIOD_RANGE_JS] == {"start": "20260201", "end": "20260228"}


async def test_set_collect_period_override_leap_february():
    page = _FakePage({cjs.SET_PERIOD_RANGE_JS: True})
    await csteps.set_collect_period(page, "202402")  # 2024-02(윤년 → 29일)
    assert page.eval_args[cjs.SET_PERIOD_RANGE_JS] == {"start": "20240201", "end": "20240229"}


# ── run_collect_query ─────────────────────────────────────────────────────────
async def test_run_collect_query_clicks_visible_lookup():
    page = _FakePage({cjs.VISIBLE_LOOKUP_BTN_RECT_JS: {"x": 33, "y": 44}})
    await csteps.run_collect_query(page)
    assert (33, 44) in page.clicks


# ── set_collect_gubun_card ────────────────────────────────────────────────────
async def test_set_collect_gubun_card_uses_kendo_ok():
    from nbkit.omnisol import js_lib

    page = _FakePage({js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS: {"ok": True, "val": "52"}})
    assert await csteps.set_collect_gubun_card(page) is True
    assert page.eval_args[js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS] == {
        "selector": "#ABDOCU_FG_CD",
        "text": "카드",
    }


# ── Phase C 프리미티브(child) ─────────────────────────────────────────────────
class _FakeChild:
    def __init__(self, responses: dict) -> None:
        self._responses = responses
        self.clicks: list = []
        self.keys: list = []
        self.typed: list = []
        self.eval_args: dict = {}
        self.mouse = _FakeMouse(self.clicks)
        self.keyboard = self._KB(self)

    class _KB:
        def __init__(self, c) -> None:
            self._c = c

        async def press(self, k):
            self._c.keys.append(k)

        async def type(self, t):
            self._c.typed.append(t)

    async def evaluate(self, js_src, arg=None):
        self.eval_args[js_src] = arg
        val = self._responses.get(js_src)
        return val(arg) if callable(val) else val

    async def wait_for_timeout(self, ms):
        return None


async def test_fill_refdoc_docno_clears_then_types_and_readback_ok():
    child = _FakeChild(
        {
            cjs.REFDOC_DOCNO_INPUT_RECT_JS: {"x": 5, "y": 6},
            cjs.REFDOC_DOCNO_VALUE_JS: "GW1",  # readback 일치 → 1회 성공
        }
    )
    ok = await csteps.fill_refdoc_docno(child, "GW1")
    assert ok is True
    assert child.keys.count("Backspace") == csteps.REFDOC_CLEAR_BACKSPACES  # 1회 시도.
    assert "End" in child.keys and child.typed == ["GW1"]


async def test_fill_refdoc_docno_retries_on_mismatch_then_gives_up():
    child = _FakeChild(
        {
            cjs.REFDOC_DOCNO_INPUT_RECT_JS: {"x": 5, "y": 6},
            cjs.REFDOC_DOCNO_VALUE_JS: "STALE",  # 항상 불일치 → 2회 시도 후 False.
        }
    )
    ok = await csteps.fill_refdoc_docno(child, "GW1")
    assert ok is False
    assert child.typed == ["GW1", "GW1"]  # 2회 시도.


async def test_fill_refdoc_docno_no_input_returns_false():
    child = _FakeChild({cjs.REFDOC_DOCNO_INPUT_RECT_JS: None})
    assert await csteps.fill_refdoc_docno(child, "GW1") is False


async def test_move_refdoc_down_uses_rect_when_present():
    child = _FakeChild({cjs.REFDOC_DOWN_BTN_RECT_JS: {"x": 480, "y": 415}})
    await csteps.move_refdoc_down(child)
    assert (480, 415) in child.clicks


async def test_move_refdoc_down_falls_back_to_coord():
    child = _FakeChild({cjs.REFDOC_DOWN_BTN_RECT_JS: None})
    await csteps.move_refdoc_down(child)
    assert (cjs.REFDOC_DOWN_BTN_FALLBACK["x"], cjs.REFDOC_DOWN_BTN_FALLBACK["y"]) in child.clicks


async def test_select_refdoc_row_passes_gwdocu_arg():
    child = _FakeChild({cjs.REFDOC_SELECT_ROW_JS: True})
    assert await csteps.select_refdoc_row(child, "GW1") is True
    assert child.eval_args[cjs.REFDOC_SELECT_ROW_JS] == "GW1"


async def test_click_refdoc_confirm_clicks_when_present():
    child = _FakeChild({cjs.REFDOC_CONFIRM_BTN_RECT_JS: {"x": 9, "y": 9}})
    assert await csteps.click_refdoc_confirm(child) is True
    assert (9, 9) in child.clicks


async def test_click_refdoc_confirm_none_returns_false():
    child = _FakeChild({cjs.REFDOC_CONFIRM_BTN_RECT_JS: None})
    assert await csteps.click_refdoc_confirm(child) is False
    assert child.clicks == []


async def test_close_refdoc_dialog_clicks_x():
    child = _FakeChild({cjs.REFDOC_CLOSE_BTN_RECT_JS: {"x": 7, "y": 8}})
    assert await csteps.close_refdoc_dialog(child) is True
    assert (7, 8) in child.clicks
