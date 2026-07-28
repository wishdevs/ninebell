"""voucher-receivable 팝업 프리미티브(_open_picker·_apply_popup) 단위 검증 — 브라우저 없이.

2026-07-24 회귀: 조회조건 피커들은 전부 '최상단 k-window'를 조작한다. 앞 피커(부서) 팝업이
'적용' 후 실제로 닫혔는지 검증하지 않으면, 느린 세션에서 부서 팝업(46행)이 남은 채 전자결재상태
피커가 그 팝업을 읽어 '저장'을 못 찾았다({ok:True, idxs:[], n:46}). 팝업 개수 증감(POPUP_COUNT_JS)
으로 열림/닫힘을 검증하도록 고쳤고, 이 테스트가 그 계약을 고정한다.
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


class _SeqPage:
    """POPUP_COUNT_JS 는 시퀀스에서 하나씩(소진되면 마지막 값 유지) — 팝업 개수 변화를 시뮬한다.
    나머지 JS 는 responses 고정 응답."""

    def __init__(self, count_seq: list[int], responses: dict | None = None) -> None:
        self._counts = list(count_seq)
        self._responses = responses or {}
        self.clicks: list = []
        self.mouse = _FakeMouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.POPUP_COUNT_JS:
            return self._counts.pop(0) if len(self._counts) > 1 else (self._counts[0] if self._counts else 0)
        val = self._responses.get(js_src)
        return val(arg) if callable(val) else val

    async def wait_for_timeout(self, ms):
        return None


# ── _apply_popup: '적용' 후 팝업이 실제로 닫혔는지 검증 ────────────────────────────
async def test_apply_popup_true_when_popup_closes():
    # before=1, 클릭 후 개수 0 → 닫힘 확정 True, 클릭 1회.
    page = _SeqPage([1, 0], {vjs.POPUP_APPLY_BTN_JS: {"x": 5, "y": 6}})
    ok = await vsteps._apply_popup(page)
    assert ok is True
    assert page.clicks == [(5, 6)]


async def test_apply_popup_false_when_popup_stays_open_and_reclicks():
    # 개수가 계속 1(안 닫힘) → False. reclick_after_ms 경과 후 '적용' 재클릭(총 2회).
    page = _SeqPage([1], {vjs.POPUP_APPLY_BTN_JS: {"x": 5, "y": 6}})
    ok = await vsteps._apply_popup(page, close_cap_ms=600, interval_ms=100, reclick_after_ms=300)
    assert ok is False
    assert page.clicks == [(5, 6), (5, 6)]  # 최초 적용 + 재클릭.


async def test_apply_popup_false_when_no_apply_button():
    page = _SeqPage([1], {vjs.POPUP_APPLY_BTN_JS: None})
    assert await vsteps._apply_popup(page) is False
    assert page.clicks == []


# ── _open_picker: 새 팝업이 실제로 떴는지(개수 증가) 검증 ──────────────────────────
async def test_open_picker_true_when_fresh_popup_appears():
    # before=0 → 클릭 후 개수 1(증가) + 그리드 ready → True.
    page = _SeqPage(
        [0, 1],
        {vjs.FIELD_SEARCH_BTN_RECT_JS: {"x": 7, "y": 8}, vjs.POPUP_GRID_READY_JS: True},
    )
    ok = await vsteps._open_picker(page, "전자결재상태", ready_cap_ms=600, ready_interval_ms=100)
    assert ok is True
    assert page.clicks == [(7, 8)]


async def test_open_picker_false_on_stale_popup_no_new_window():
    # ⚠ 회귀 핵심: 앞 팝업(부서)이 안 닫혀 before=1. 돋보기 클릭이 그 팝업 뒤라 새 팝업이 안 뜸
    # (개수 계속 1). 최상단 그리드는 ready 여도 '증가 없음'이라 False → 잘못된 팝업 오독 차단.
    page = _SeqPage(
        [1],
        {vjs.FIELD_SEARCH_BTN_RECT_JS: {"x": 7, "y": 8}, vjs.POPUP_GRID_READY_JS: True},
    )
    ok = await vsteps._open_picker(page, "전자결재상태", ready_cap_ms=400, ready_interval_ms=100)
    assert ok is False


async def test_open_picker_false_when_no_search_button():
    page = _SeqPage([0], {vjs.FIELD_SEARCH_BTN_RECT_JS: None})
    assert await vsteps._open_picker(page, "전자결재상태", ready_cap_ms=400) is False
    assert page.clicks == []


# ── set_dept_all: 목록 로드 폴링 + 전체선택 반영 검증 ─────────────────────────────
class _DeptPage:
    """set_dept_all 전체 흐름 시뮬 — 팝업 개수(돋보기(10,10)=열림/적용(20,20)=닫힘),
    checkAll n 시퀀스(로드 레이스 재현), 표시값(전체선택 반영 검증)."""

    def __init__(self, check_all_ns: list[int], display: str = "인사/기획팀 외 45건") -> None:
        self._ns = list(check_all_ns)
        self._display = display
        self.clicks: list = []
        self.mouse = _FakeMouse(self.clicks)
        self.check_all_calls = 0

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.NOTICE_POPUP_BOXES_JS:
            return None
        if js_src == vjs.POPUP_COUNT_JS:
            opened = (10, 10) in self.clicks
            closed = (20, 20) in self.clicks
            return 1 if (opened and not closed) else 0
        if js_src == vjs.FIELD_SEARCH_BTN_RECT_JS:
            return {"x": 10, "y": 10}
        if js_src == vjs.POPUP_GRID_READY_JS:
            return True
        if js_src == vjs.POPUP_CHECK_ALL_JS:
            self.check_all_calls += 1
            n = self._ns.pop(0) if len(self._ns) > 1 else (self._ns[0] if self._ns else 0)
            return {"ok": True, "n": n}
        if js_src == vjs.POPUP_APPLY_BTN_JS:
            return {"x": 20, "y": 20}
        if js_src == vjs.FIELD_DISPLAY_JS:
            return self._display
        raise AssertionError(f"unexpected evaluate: {js_src[:50]!r}")

    async def wait_for_timeout(self, ms):
        return None


async def test_set_dept_all_polls_checkall_until_rows_loaded():
    # ⚠ 회귀 핵심: 그리드 부착 직후 checkAll 이 0건(데이터 미로드)이어도, n>0 이 될 때까지
    # 폴링해 실제로 46건을 체크한 뒤 적용한다('전체선택 안 됨' 방지).
    page = _DeptPage([0, 0, 46])
    res = await vsteps.set_dept_all(page)
    assert res["ok"] is True and res["n"] == 46
    assert page.check_all_calls >= 3


async def test_set_dept_all_fails_when_selection_not_reflected():
    # 적용 후 표시값이 (재시도해도) 비면 전체선택 미반영 → 잘못된 부서 필터 조회를 막고 실패.
    page = _DeptPage([46], display="")
    res = await vsteps.set_dept_all(page)
    assert res["ok"] is False and "확인 실패" in res["reason"]


async def test_set_dept_all_unreadable_display_passes_with_warning():
    # 라벨/피커를 못 읽는 세션(리더 null)은 '값이 다름'이 아니라 **확인 불가** — 하드 실패로
    # 플로우를 끊지 않고 warn 을 얹어 통과시킨다(리더 오탐이 조회를 막지 않게).
    page = _DeptPage([46], display=None)
    res = await vsteps.set_dept_all(page)
    assert res["ok"] is True and "확인 불가" in res["warn"]


async def test_set_dept_all_success():
    page = _DeptPage([46])
    res = await vsteps.set_dept_all(page)
    assert res["ok"] is True and res["n"] == 46 and res["display"]


# ══════════════════════════════════════════════════════════════════════════════
# 값 세팅 스텝의 '반영 확인' 계약(2026-07-27) — 확인 커널(nbkit.omnisol.verify) 사용부.
#   불일치(확인은 됐는데 값이 다름) = 하드 실패 / 확인 불가(리더가 못 읽음) = warn 후 통과.
# ══════════════════════════════════════════════════════════════════════════════
class _FieldPage:
    """드롭다운·표시값·기간 리더를 시나리오로 돌려주는 스텁(팝업류는 즉시 성공 처리)."""

    def __init__(
        self, *, selected="미결", display="저장", period=None, set_ok=True, popup_rows=("저장",)
    ) -> None:
        self._selected = selected
        self._display = display
        self._period = period
        self._set_ok = set_ok
        self._popup_rows = popup_rows
        self.set_calls = 0
        self.clicks: list = []
        self.mouse = _FakeMouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS:
            self.set_calls += 1
            return {"ok": self._set_ok, "val": "1"}
        if js_src == js_lib.SELECTED_TEXT_JS:
            return {"ok": True, "text": self._selected, "value": "1"} if self._selected is not None else {"ok": False}
        if js_src == js_lib.FIELD_DISPLAY_JS:
            return self._display
        if js_src == js_lib.PERIOD_VALUE_JS:
            return self._period
        if js_src == vjs.CLEAR_WRITER_JS or js_src == vjs.SET_PERIOD_THIS_MONTH_JS:
            return True
        # 피커 팝업 경로(전자결재상태·전표유형) — 열기/체크/적용을 성공으로 통과시킨다.
        if js_src == js_lib.NOTICE_POPUP_BOXES_JS:
            return None
        if js_src == vjs.POPUP_COUNT_JS:
            # 돋보기(10,10) 클릭 = 열림 / 적용(20,20) 클릭 = 닫힘(개수 증감으로 판정).
            return 1 if ((10, 10) in self.clicks and (20, 20) not in self.clicks) else 0
        if js_src == vjs.FIELD_SEARCH_BTN_RECT_JS:
            return {"x": 10, "y": 10}
        if js_src == vjs.POPUP_GRID_READY_JS:
            return True
        if js_src == vjs.POPUP_CHECK_ROWS_JS:
            targets = arg[0] if arg else []
            return {"ok": True, "idxs": [{"t": t, "idx": i} for i, t in enumerate(targets)]}
        if js_src == vjs.POPUP_APPLY_BTN_JS:
            return {"x": 20, "y": 20}
        if js_src == vjs.FIELD_LABEL_VISIBLE_JS:
            return True
        raise AssertionError(f"unexpected evaluate: {js_src[:50]!r}")

    async def wait_for_timeout(self, ms):
        return None


async def test_set_docu_status_confirms_actual_selection():
    page = _FieldPage(selected="미결")
    res = await vsteps.set_docu_status(page)
    assert res["ok"] is True and "warn" not in res


async def test_set_docu_status_fails_when_widget_reverts_value():
    # 세팅 JS 는 ok 를 냈지만 위젯이 값을 되돌린 경우 — 재세팅 재시도 후에도 다르면 하드 실패.
    page = _FieldPage(selected="전체")
    res = await vsteps.set_docu_status(page)
    assert res["ok"] is False and "확인 실패" in res["reason"]
    # 되돌려지는 값이라 재시도 때 재세팅한다(최초 1회 + 재시도 3회).
    assert page.set_calls > 1


async def test_set_docu_status_unreadable_select_passes_with_warning():
    page = _FieldPage(selected=None)  # 리더가 select 를 못 찾음 = 확인 불가
    res = await vsteps.set_docu_status(page)
    assert res["ok"] is True and "확인 불가" in res["warn"]


async def test_clear_writer_requires_empty_display():
    assert (await vsteps.clear_writer(_FieldPage(display="")))["ok"] is True
    failed = await vsteps.clear_writer(_FieldPage(display="홍길동"))
    assert failed["ok"] is False and "확인 실패" in failed["reason"]


async def test_clear_writer_null_display_is_unknown_not_success():
    # ⚠ null(필드 미발견)을 '비었다'로 통과시키면 clear 실패를 못 잡는다 — 확인 불가로 분류.
    res = await vsteps.clear_writer(_FieldPage(display=None))
    assert res["ok"] is True and "확인 불가" in res["warn"]


async def test_set_period_this_month_confirms_browser_current_month():
    page = _FieldPage(period={"found": True, "ym": ["202607", "202607"], "now": "202607"})
    assert (await vsteps.set_period_this_month(page))["ok"] is True

    stale = _FieldPage(period={"found": True, "ym": ["202606", "202606"], "now": "202607"})
    res = await vsteps.set_period_this_month(stale)
    assert res["ok"] is False and "확인 실패" in res["reason"]


async def test_set_period_unreadable_widget_passes_with_warning():
    page = _FieldPage(period={"found": False, "reason": "no-field", "now": "202607"})
    res = await vsteps.set_period_this_month(page)
    assert res["ok"] is True and "확인 불가" in res["warn"]


async def test_set_gwaprvlst_requires_form_reflection():
    # 팝업 안 checkRow 성공만으론 부족 — 폼 표시값이 비면 실패로 본다.
    ok = await vsteps.set_gwaprvlst(_FieldPage(display="저장"))
    assert ok["ok"] is True and ok["display"] == "저장"
    empty = await vsteps.set_gwaprvlst(_FieldPage(display=""))
    assert empty["ok"] is False and "확인 실패" in empty["reason"]


async def test_set_docu_types_requires_form_reflection():
    ok = await vsteps.set_docu_types(_FieldPage(display="일반"), ("일반",))
    assert ok["ok"] is True and ok["checked"]
    empty = await vsteps.set_docu_types(_FieldPage(display=""), ("일반",))
    assert empty["ok"] is False and "확인 실패" in empty["reason"]
