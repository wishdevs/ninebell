"""쓰기 계약(write-contract) — "쓰기 JS 는 성공하는데 반영은 영원히 안 되는" 페이지 검증.

2026-08-07 무결성 감사의 회귀 장치: voucher 백본의 모든 **상태변경 스텝**은
  (i) 독립 리더로 반영을 재확인하고, (ii) 미반영이면 재적용(reapply/attempt 재실행)하고,
  (iii) 예산 소진 후에는 {ok:False, reason}으로 **명시적으로** 실패해야 한다.
어떤 스텝이든 이 페이지에서 ok:True 를 돌려주면 '조용한 실패'(선택 안 됐는데 성공 보고) —
DB 실측에서 성공 런에 묻힌 소프트 실패 10건의 재발 방지 계약이다.

새 상태변경 스텝을 추가하면 CASES 에 1행을 추가하는 것이 관례다.
"""

from __future__ import annotations

import pytest

from app.agents.voucher_receivable import js as vjs
from app.agents.voucher_receivable import steps as vsteps
from nbkit.omnisol import js_lib

pytestmark = pytest.mark.asyncio


class _FakeMouse:
    def __init__(self, sink: list) -> None:
        self._sink = sink

    async def click(self, x, y):
        self._sink.append((x, y))


class _NeverReflectPage:
    """모든 쓰기 JS 는 '성공'을 돌려주지만, 어떤 리더도 목표값을 보여주지 않는 페이지.

    display: FIELD_DISPLAY_JS 가 돌려줄 값 — 세팅 계열은 ""(미반영), 비움 계열은
    "홍길동"(안 비워짐)을 준다. 팝업 개수는 열기/적용/닫기 클릭 수로 모델링해
    attempt 전체 재실행(재열기 사이클)을 지원한다.
    """

    def __init__(self, *, display: str = "") -> None:
        self._display = display
        self.writes = 0  # 쓰기 JS 호출 수 — 재적용(reapply) 발화 증거.
        self.closes = 0
        self.clicks: list = []
        self.mouse = _FakeMouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.DOCU_ST_READY_JS:
            return {"sel": True, "widget": True}
        if js_src == js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS:
            self.writes += 1
            return {"ok": True, "val": "1"}
        if js_src == js_lib.SELECTED_TEXT_JS:
            return {"ok": True, "text": "전체", "value": "0"}  # 목표('미결')와 영원히 다름.
        if js_src in (vjs.CLEAR_WRITER_JS, vjs.SET_PERIOD_THIS_MONTH_JS):
            self.writes += 1
            return True
        if js_src == vjs.SET_PERIOD_RANGE_JS:
            self.writes += 1
            return True
        if js_src == vjs.PERIOD_VALUE_JS:
            return {"start": "19990101", "end": "19990131"}  # 위젯이 늘 되돌림.
        if js_src == js_lib.PERIOD_VALUE_JS:
            return {"found": True, "ym": ["199901", "199901"], "now": "202608"}
        if js_src == js_lib.FIELD_DISPLAY_JS:
            return self._display
        if js_src == js_lib.NOTICE_POPUP_BOXES_JS:
            return None
        if js_src == vjs.POPUP_COUNT_JS:
            opens = self.clicks.count((10, 10))
            applies = self.clicks.count((20, 20))
            return max(0, opens - applies - self.closes)
        if js_src == js_lib.PICKER_CLOSE_JS:
            self.closes += 1
            return True
        if js_src == vjs.FIELD_SEARCH_BTN_RECT_JS:
            return {"x": 10, "y": 10}
        if js_src == vjs.POPUP_GRID_READY_JS:
            return True
        if js_src == vjs.POPUP_CHECK_ROWS_JS:
            self.writes += 1
            targets = arg[0] if arg else []
            return {"ok": True, "idxs": [{"t": t, "idx": i} for i, t in enumerate(targets)], "n": 5}
        if js_src == vjs.POPUP_CHECK_ALL_JS:
            self.writes += 1
            return {"ok": True, "n": 46}
        if js_src == vjs.POPUP_APPLY_BTN_JS:
            return {"x": 20, "y": 20}
        if js_src == vjs.FIELD_LABEL_VISIBLE_JS:
            return True
        if js_src in (vjs.EXPAND_TOGGLE_RECT_JS, vjs.EXPAND_TOGGLE_RECTS_JS):
            return []
        raise AssertionError(f"unexpected evaluate: {str(js_src)[:60]!r}")

    async def wait_for_timeout(self, ms):
        return None


CASES = [
    ("set_period", lambda p: vsteps.set_period(p, "20260701", "20260831"), ""),
    ("set_period_this_month", lambda p: vsteps.set_period_this_month(p), ""),
    ("clear_writer", lambda p: vsteps.clear_writer(p), "홍길동"),
    ("set_docu_status", lambda p: vsteps.set_docu_status(p), ""),
    ("set_dept_all", lambda p: vsteps.set_dept_all(p), ""),
    ("set_gwaprvlst", lambda p: vsteps.set_gwaprvlst(p), ""),
    ("set_docu_types", lambda p: vsteps.set_docu_types(p, ("내수구매",)), ""),
]


@pytest.mark.parametrize("name,call,display", CASES, ids=[c[0] for c in CASES])
async def test_write_never_reflected_is_reported_not_swallowed(name, call, display):
    page = _NeverReflectPage(display=display)
    res = await call(page)
    assert res["ok"] is False, f"{name}: 반영이 안 됐는데 ok:True — 조용한 실패(계약 위반)"
    assert res.get("reason"), f"{name}: 실패에 reason 이 없다(구조화 실패 계약 위반)"
    assert page.writes >= 2, f"{name}: 미반영인데 재적용(reapply)이 발화하지 않았다"
