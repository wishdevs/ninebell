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


async def test_open_picker_normalizes_double_open():
    """⚠ 이중 오픈 정규화(2026-08-07): 첫 클릭이 먹었는데 렌더 지연으로 재클릭까지 나가 팝업이
    2개 뜨면, 초과분을 닫아 '새 팝업 1개' 불변식을 복원한다(잔존 팝업이 다음 피커를 오염시키는
    2026-07-24 사고의 재유입 뒷문 차단)."""

    class _DoubleOpenPage(_SeqPage):
        def __init__(self) -> None:
            super().__init__(
                [], {vjs.FIELD_SEARCH_BTN_RECT_JS: {"x": 7, "y": 8}, vjs.POPUP_GRID_READY_JS: True}
            )
            self.closes = 0

        async def evaluate(self, js_src, arg=None):
            if js_src == vjs.POPUP_COUNT_JS:
                return (2 if self.clicks else 0) - self.closes  # 클릭 1번에 팝업 2개 출현 시뮬.
            if js_src == js_lib.PICKER_CLOSE_JS:
                self.closes += 1
                return True
            return await super().evaluate(js_src, arg)

    page = _DoubleOpenPage()
    ok = await vsteps._open_picker(page, "전자결재상태", ready_cap_ms=400, ready_interval_ms=50)
    assert ok is True
    assert page.closes == 1  # 초과분 1개만 닫았다(새 팝업 1개는 유지).


async def test_open_picker_reclicks_when_first_click_swallowed():
    # ⚠ 회귀 핵심(2026-08-01 전표유형 라이브 실증): 확장 애니메이션 중 좌표로 클릭이 빗나가면
    # 팝업이 안 뜸 — 출현 관찰창 소진 후 fresh 좌표로 재클릭해 열어야 한다.
    class _SwallowFirstClickPage(_SeqPage):
        async def evaluate(self, js_src, arg=None):
            if js_src == vjs.POPUP_COUNT_JS:
                return 1 if len(self.clicks) >= 2 else 0  # 두 번째 클릭부터 팝업 출현.
            return await super().evaluate(js_src, arg)

    page = _SwallowFirstClickPage(
        [], {vjs.FIELD_SEARCH_BTN_RECT_JS: {"x": 7, "y": 8}, vjs.POPUP_GRID_READY_JS: True}
    )
    ok = await vsteps._open_picker(page, "전표유형", ready_cap_ms=800, ready_interval_ms=50)
    assert ok is True
    assert page.clicks == [(7, 8), (7, 8)]  # 최초 클릭(삼킴) + 재클릭.


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
        self.closed_via_js = False  # 실패 정리(_fail_close → PICKER_CLOSE_JS) 발화 기록.
        self.clicks: list = []
        self.mouse = _FakeMouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.DOCU_ST_READY_JS:
            return {"sel": True, "widget": True}  # 준비 게이트 즉시 통과.
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
            # 돋보기(10,10) 클릭 = 열림 / 적용(20,20) 클릭 또는 닫기 JS = 닫힘(개수 증감 판정).
            opened = (10, 10) in self.clicks and (20, 20) not in self.clicks
            return 1 if (opened and not self.closed_via_js) else 0
        if js_src == js_lib.PICKER_CLOSE_JS:
            self.closed_via_js = True
            return True
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


async def test_set_docu_status_first_set_failure_recovers_via_reapply():
    """⚠ 준비/재시도 도달(2026-08-07): 1차 세팅 JS 가 실패해도 즉시 하드 실패하지 않고
    confirm_select 의 재세팅(reapply)으로 회복한다 — 종전엔 1차 실패가 reapply 에 도달조차
    못 하는 구조였다(폼 리로드 순간의 단발 실패가 곧장 런 실패로)."""

    class _FlakySetPage(_FieldPage):
        async def evaluate(self, js_src, arg=None):
            if js_src == js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS:
                self.set_calls += 1
                return {"ok": self.set_calls >= 2, "val": "1"}  # 1차만 실패.
            if js_src == js_lib.SELECTED_TEXT_JS:
                # 세팅이 실제로 먹은 뒤에만 목표 텍스트가 읽힌다.
                if self.set_calls >= 2:
                    return {"ok": True, "text": "미결", "value": "1"}
                return {"ok": True, "text": "전체", "value": "0"}
            return await super().evaluate(js_src, arg)

    page = _FlakySetPage()
    res = await vsteps.set_docu_status(page)
    assert res["ok"] is True and "warn" not in res
    assert page.set_calls >= 2  # 1차 실패 후 재세팅이 실제로 발화했다.


async def test_set_docu_status_hard_fails_when_select_never_appears():
    """select 자체가 끝내 출현하지 않으면(폼 미로드) 명확한 사유로 하드 실패한다."""

    class _NoSelectPage(_FieldPage):
        async def evaluate(self, js_src, arg=None):
            if js_src == vjs.DOCU_ST_READY_JS:
                return {"sel": False, "widget": False}
            return await super().evaluate(js_src, arg)

    res = await vsteps.set_docu_status(_NoSelectPage())
    assert res["ok"] is False and "select 미출현" in res["reason"]


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


# ── 팝업 행 도착 레이스(2026-08-01 전자결재상태 라이브 실증) ─────────────────────────
class _LateRowsPage(_FieldPage):
    """그리드 부착 후 행 도착이 늦는 팝업 재현 — 처음 empty_calls 회는 {ok, n:0} 을 돌려주고
    이후 _FieldPage 의 정상 매칭으로 위임한다(행이 영영 안 오면 empty_calls 를 크게)."""

    def __init__(self, *, empty_calls: int, **kw) -> None:
        super().__init__(**kw)
        self.rows_calls = 0
        self._empty_calls = empty_calls

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.POPUP_CHECK_ROWS_JS:
            self.rows_calls += 1
            if self.rows_calls <= self._empty_calls:
                return {"ok": True, "idxs": [], "n": 0}
        return await super().evaluate(js_src, arg)


async def test_gwaprvlst_polls_until_popup_rows_arrive():
    # ⚠ 회귀 핵심: _open_picker 는 '그리드 부착'까지만 보장 — 행 도착 전 단발 checkRow 가
    # {ok:True, n:0} 실패로 오판되던 레이스(고정 1200ms 선대기 제거로 노출). 도착까지 폴링한다.
    page = _LateRowsPage(empty_calls=3, display="저장")
    res = await vsteps.set_gwaprvlst(page)
    assert res["ok"] is True and page.rows_calls >= 4


async def test_gwaprvlst_fails_clearly_when_rows_never_load():
    page = _LateRowsPage(empty_calls=10_000, display="저장")
    res = await vsteps.set_gwaprvlst(page)
    assert res["ok"] is False and "행이 로드되지 않았습니다" in res["reason"]


async def test_gwaprvlst_failure_closes_leftover_popup():
    """⚠ 실패 경로 팝업 정리(2026-08-07): 팝업을 연 뒤 실패하면 열린 채 반환하지 않고 닫는다 —
    잔존 팝업이 다음 피커의 wins[last] 타깃을 오염시키는 경로 차단(trip_domestic 규율 이식)."""
    page = _LateRowsPage(empty_calls=10_000, display="저장")
    res = await vsteps.set_gwaprvlst(page)
    assert res["ok"] is False
    assert page.closed_via_js is True  # PICKER_CLOSE_JS 로 잔존 팝업을 실제로 닫았다.
    assert "행이 로드되지 않았습니다" in res["reason"]  # 정리 실패가 원래 사유를 덮지 않는다.


async def test_gwaprvlst_target_missing_fails_fast_without_full_polling():
    # 행은 로드됐는데(n>0) 대상만 없는 경우 — 기다려도 안 생기므로 즉시 실패해야 한다.
    class _NoMatchPage(_FieldPage):
        def __init__(self) -> None:
            super().__init__(display="저장")
            self.rows_calls = 0

        async def evaluate(self, js_src, arg=None):
            if js_src == vjs.POPUP_CHECK_ROWS_JS:
                self.rows_calls += 1
                return {"ok": True, "idxs": [], "n": 7}
            return await super().evaluate(js_src, arg)

    page = _NoMatchPage()
    res = await vsteps.set_gwaprvlst(page)
    assert res["ok"] is False and "찾지 못했습니다" in res["reason"]
    assert page.rows_calls == 1  # n>0 이면 폴링 없이 즉시 판정.


async def test_docu_types_polls_until_popup_rows_arrive():
    page = _LateRowsPage(empty_calls=2, display="일반")
    res = await vsteps.set_docu_types(page, ("일반",))
    assert res["ok"] is True and page.rows_calls >= 3


async def test_gwaprvlst_reapplies_whole_attempt_when_display_not_reflected():
    """⚠ attempt-as-reapply(2026-08-07, voucher_card set_collect_dept_all 이식): 적용까지 됐는데
    폼 표시값이 안 붙었으면 열기→체크→적용 **전체를 재실행**해 회복한다 — '튕겨나간 적용은
    기다린다고 붙지 않는다'(같은 화면 부서 스텝의 실측 규율)."""

    class _LateDisplayPage(_FieldPage):
        def __init__(self) -> None:
            super().__init__(display="")
            self.display_reads = 0

        async def evaluate(self, js_src, arg=None):
            if js_src == js_lib.FIELD_DISPLAY_JS:
                self.display_reads += 1
                return "저장" if self.display_reads >= 2 else ""  # 2회차부터 반영.
            if js_src == vjs.POPUP_COUNT_JS:
                # 재열기 사이클 지원 — 열기(10,10)마다 +1, 적용(20,20)마다 -1, 닫기 JS -1.
                opens = self.clicks.count((10, 10))
                applies = self.clicks.count((20, 20))
                return max(0, opens - applies - (1 if self.closed_via_js else 0))
            return await super().evaluate(js_src, arg)

    page = _LateDisplayPage()
    res = await vsteps.set_gwaprvlst(page)
    assert res["ok"] is True and res["display"] == "저장"
    assert page.clicks.count((10, 10)) >= 2  # 돋보기 재클릭 = attempt 전체 재실행 증거.


async def test_docu_types_reensures_visibility_and_retries_open():
    # ⚠ 재접힘 레이스: 가시성 확인 통과 후 rect 를 읽는 순간 패널이 접혀 null — 첫 열기가
    # 실패해도 가시성 재확보 후 1회 재시도로 성공해야 한다.
    class _CollapseOncePage(_FieldPage):
        def __init__(self) -> None:
            super().__init__(display="일반")
            self.rect_calls = 0

        async def evaluate(self, js_src, arg=None):
            if js_src == vjs.FIELD_SEARCH_BTN_RECT_JS:
                self.rect_calls += 1
                if self.rect_calls <= 4:  # 첫 _open_picker 의 null 재관찰 전부 실패시킴.
                    return None
            return await super().evaluate(js_src, arg)

    page = _CollapseOncePage()
    res = await vsteps.set_docu_types(page, ("일반",))
    assert res["ok"] is True
    assert page.rect_calls >= 5  # 첫 시도 null×4 → 재시도에서 유효 rect.


# ── run_query: 조회 rowcount 레이스(거짓 0건) 회귀 고정 ───────────────────────────
class _QueryPage:
    """조회 클릭 후 서버 응답이 늦게 도착하는 그리드 — 도착 전 rowcount 는 클릭 전 값 그대로.

    2026-08-06 포렌식: 예전 run_query 는 클릭 ≈160ms 뒤 첫 읽기의 0건을 그대로 성공 확정해
    "어떨 땐 되고 어떨 땐 안 되는" 거짓 0건(조용한 '대상 없음' 종료)을 만들었다.
    이 스텁이 그 지연 도착을 재현한다.
    """

    def __init__(self, *, before: int, after: int, arrive_on: int) -> None:
        self.rowcount = before
        self._after = after
        self._arrive_on = arrive_on  # 몇 번째 ROWCOUNT 읽기부터 새 결과가 보이는가
        self.reads = 0
        self.clicks = 0

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.ROWCOUNT_BY_INDEX_JS:
            self.reads += 1
            if self.reads > self._arrive_on:
                self.rowcount = self._after
            return self.rowcount
        if "el.click()" in str(js_src):  # js_click(BTN_LOOKUP)
            self.clicks += 1
            return True
        return None


async def test_run_query_waits_for_late_result_instead_of_zero():
    """서버 응답이 늦어도 0건을 조기 확정하지 않고 새 결과(241건)를 기다린다."""
    page = _QueryPage(before=0, after=241, arrive_on=2)  # 기준 스냅샷+1회는 아직 0
    r = await vsteps.run_query(page)
    assert r == {"ok": True, "rowcount": 241, "basis": "changed"}
    assert page.clicks == 1  # 재조회 없이 첫 조회에서 확정


async def test_run_query_holds_zero_until_schedule_exhausted():
    """0건은 HEAVY 스케줄을 전부 소진한 뒤에만 확정 — basis='exhausted' 근거를 남긴다."""
    page = _QueryPage(before=0, after=0, arrive_on=99)
    r = await vsteps.run_query(page)
    assert r == {"ok": True, "rowcount": 0, "basis": "exhausted"}
    # 기준 스냅샷 1회 + 확인 커널 HEAVY 4회 = 5회(조기 확정이면 2회에서 끝났다)
    assert page.reads == 1 + 4


async def test_run_query_requeries_once_then_fails_when_grid_unreadable():
    """그리드를 끝내 못 읽으면(-1) 재조회 1회 후 실패 — 거짓 0건 대신 명시적 실패."""
    page = _QueryPage(before=-1, after=-1, arrive_on=0)
    r = await vsteps.run_query(page)
    assert r["ok"] is False and r["rowcount"] == -1
    assert page.clicks == 2  # 재조회 1회 포함


async def test_run_query_fails_clearly_when_lookup_button_missing():
    """⚠ fire-and-forget 봉합(2026-08-07): 조회 버튼 미발견(js_click False)을 무시하면 base
    무변화 → basis='exhausted' 로 **조회 미실행이 '0건 정상완료'로 위장**된다 — 재시도 후에도
    버튼이 없으면 명시적으로 실패해야 한다."""

    class _NoButtonPage(_QueryPage):
        async def evaluate(self, js_src, arg=None):
            if "el.click()" in str(js_src):
                self.clicks += 1
                return False  # 버튼 미발견.
            return await super().evaluate(js_src, arg)

    page = _NoButtonPage(before=0, after=0, arrive_on=99)
    r = await vsteps.run_query(page)
    assert r["ok"] is False and "버튼" in r["reason"]
    assert page.reads <= 1  # 기준 스냅샷만 — 버튼 없이 rowcount 폴링으로 위장하지 않는다.
