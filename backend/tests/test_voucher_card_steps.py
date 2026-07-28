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
from app.agents.voucher_receivable import js as vr_js
from nbkit.omnisol import js_lib

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
        self.clicked_selectors: list = []
        self.eval_args: dict = {}
        self.mouse = _FakeMouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        self.eval_args[js_src] = arg
        val = self._responses.get(js_src)
        return val(arg) if callable(val) else val

    async def click(self, selector, timeout=None):
        """Playwright 셀렉터 클릭(탭 열기·탭 복귀) — 셀렉터만 기록한다."""
        self.clicked_selectors.append(selector)

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


async def test_read_payment_map_strips_surrounding_whitespace():
    # 그리드 표기값 앞뒤 공백을 정규화해 맵 키/값에 담는다 — loop_approvals lookup(strip)과 정합.
    rows = [{"ABDOCU_NO": "  RN1  ", "GWDOCU_NO": " GW1 "}]
    page = _FakePage({cjs.VISIBLE_MASTER_ROWS_JS: {"ok": True, "n": 1, "rows": rows}})
    res = await csteps.read_payment_map(page)
    assert res["map"] == {"RN1": "GW1"}


# ── set_collect_dept_all: 결의부서 전체선택 로드 폴링(set_dept_all 강화 이식) ─────────
class _CollectDeptPage:
    """set_collect_dept_all 흐름 시뮬 — 팝업 개수(돋보기(10,10)=열림/적용(20,20)=닫힘),
    checkAll n 시퀀스(그리드 로드 레이스 재현). 공유 프리미티브(_open_picker/_apply_popup) 경유."""

    def __init__(self, check_all_ns: list[int], display: str = "회계팀 외 45건") -> None:
        self._ns = list(check_all_ns)
        self._display = display
        self.clicks: list = []
        self.mouse = _FakeMouse(self.clicks)
        self.check_all_calls = 0

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.NOTICE_POPUP_BOXES_JS:
            return None
        if js_src == vr_js.POPUP_COUNT_JS:
            opened = (10, 10) in self.clicks
            closed = (20, 20) in self.clicks
            return 1 if (opened and not closed) else 0
        if js_src == vr_js.FIELD_SEARCH_BTN_RECT_JS:
            return {"x": 10, "y": 10}
        if js_src == vr_js.POPUP_GRID_READY_JS:
            return True
        if js_src == vr_js.POPUP_CHECK_ALL_JS:
            self.check_all_calls += 1
            n = self._ns.pop(0) if len(self._ns) > 1 else (self._ns[0] if self._ns else 0)
            return {"ok": True, "n": n}
        if js_src == vr_js.POPUP_APPLY_BTN_JS:
            return {"x": 20, "y": 20}
        if js_src == js_lib.FIELD_DISPLAY_JS:
            # 적용(20,20) 전에는 로그인 부서만, 적용 후 '외 N건'(전체선택 반영).
            return self._display if (20, 20) in self.clicks else "회계팀"
        raise AssertionError(f"unexpected evaluate: {js_src[:50]!r}")

    async def wait_for_timeout(self, ms):
        return None


async def test_set_collect_dept_all_polls_until_rows_loaded():
    # 결의부서 전체선택도 그리드 로드까지 폴링 후 checkAll(빈 그리드 0건 커밋 방지).
    page = _CollectDeptPage([0, 0, 46])
    assert await csteps.set_collect_dept_all(page) is True
    assert page.check_all_calls >= 3


async def test_set_collect_dept_all_false_when_rows_never_load():
    # 상한까지 0건이면 False — 호출부가 **하드 실패**로 다룬다(부서가 좁혀진 채 수집 금지).
    page = _CollectDeptPage([0])
    assert await csteps.set_collect_dept_all(page) is False


async def test_set_collect_dept_all_false_when_display_stays_single_dept():
    # ⚠ 회귀 핵심(2026-07-27): 적용까지 됐다고 해도 표시값이 로그인 부서 그대로면
    #   전체선택이 반영되지 않은 것 — 그 상태로 수집하면 맵이 대상과 어긋난다.
    page = _CollectDeptPage([46], display="회계팀")
    assert await csteps.set_collect_dept_all(page) is False


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


class _DocnoChild(_FakeChild):
    """문서번호 입력 — 마커 부여 후 **요소 클릭**으로 포커스를 잡는 실물 경로."""

    def __init__(self, responses: dict) -> None:
        super().__init__({cjs.REFDOC_MARK_JS: {"ok": True, "marked": "docno"}, **responses})
        self.element_clicks: list = []

    async def click(self, selector, timeout=None):
        self.element_clicks.append(selector)


async def test_fill_refdoc_docno_clears_then_types_and_readback_ok():
    child = _DocnoChild({cjs.REFDOC_DOCNO_VALUE_JS: "GW1"})  # readback 일치 → 1회 성공
    ok = await csteps.fill_refdoc_docno(child, "GW1")
    assert ok is True
    # ⚠ 좌표가 아니라 요소 클릭(입력칸이 뷰포트 밖일 때 좌표는 허공을 친다).
    assert child.element_clicks == ["[data-nb-refdoc='docno']"]
    assert child.keys.count("Backspace") == csteps.REFDOC_CLEAR_BACKSPACES  # 1회 시도.
    assert "End" in child.keys and child.typed == ["GW1"]


async def test_fill_refdoc_docno_retries_on_mismatch_then_gives_up():
    child = _DocnoChild({cjs.REFDOC_DOCNO_VALUE_JS: "STALE"})  # 항상 불일치 → 2회 시도 후 False.
    ok = await csteps.fill_refdoc_docno(child, "GW1")
    assert ok is False
    assert child.typed == ["GW1", "GW1"]  # 2회 시도.


async def test_fill_refdoc_docno_no_input_returns_false():
    # 입력칸을 못 찾으면(마커 실패) 타이핑을 시도하지 않는다.
    child = _DocnoChild({})
    child._responses[cjs.REFDOC_MARK_JS] = {"ok": False, "reason": "no-docno-input"}
    assert await csteps.fill_refdoc_docno(child, "GW1") is False
    assert child.typed == []


class _RefdocChild:
    """이동 버튼 2개 중 하나만 '아래(추가)'인 실물 시맨틱 + gridView 행 데이터 모사."""

    def __init__(self, *, works_at: int | None = 0, mark_ok: bool = True,
                 doc_no: str = "GW1", pre_docs: tuple = ()) -> None:
        self._works_at = works_at
        self._mark_ok = mark_ok
        self._doc_no = doc_no
        self._selected = list(pre_docs)
        self._marked_index = 0
        self.element_clicks: list[str] = []
        self.mouse_clicks: list = []
        self.mouse = _FakeMouse(self.mouse_clicks)

    async def evaluate(self, js_src, arg=None):
        if js_src == cjs.REFDOC_MARK_JS:
            if not self._mark_ok:
                return {"ok": False, "reason": "no-move-button"}
            self._marked_index = (arg or {}).get("index", 0)
            return {"ok": True, "marked": (arg or {}).get("kind"), "count": 2,
                    "index": self._marked_index}
        if js_src == cjs.REFDOC_GRID_ROWS_JS:
            return {"ok": True,
                    "top": {"count": 1, "docNos": [self._doc_no]},
                    "selected": {"count": len(self._selected), "docNos": list(self._selected)}}
        if js_src == cjs.REFDOC_STATE_JS:
            return {"ok": True, "total": 1, "noData": False,
                    "selectedEmpty": not self._selected,
                    "topGrid": {"x": 150, "y": 319, "w": 684, "h": 189},
                    "bottomGrid": {"x": 150, "y": 623, "w": 684, "h": 189}}
        return None

    async def click(self, selector, timeout=None):
        self.element_clicks.append(selector)
        if "move" in selector and self._marked_index == self._works_at:
            if self._doc_no not in self._selected:
                self._selected.append(self._doc_no)

    async def wait_for_timeout(self, ms):
        return None


async def test_move_refdoc_down_verifies_selected_list_filled():
    child = _RefdocChild(works_at=0)
    res = await csteps.move_refdoc_down(child, "GW1")
    # 성공 조건: 첨부 후 **1건 이상** + 그 문서번호가 목록에 실제로 존재.
    assert res["ok"] is True and res["verified"] is True and res["button_index"] == 0
    assert res["count"] == 1 and res["doc_matched"] is True
    # ⚠ 좌표가 아니라 **요소 클릭**(2026-07-27: 폴백 좌표 477,412 는 빈 공간이었다).
    assert child.element_clicks == ["[data-nb-refdoc='move']"]
    assert child.mouse_clicks == []


async def test_move_refdoc_down_tries_second_button_when_first_does_nothing():
    # 두 버튼 중 어느 쪽이 '아래'인지 DOM 으로 알 수 없어 결과검증형으로 순서대로 시도한다.
    child = _RefdocChild(works_at=1)
    res = await csteps.move_refdoc_down(child, "GW1")
    assert res["verified"] is True and res["button_index"] == 1
    assert len(child.element_clicks) == 2


async def test_move_refdoc_down_reports_failure_when_nothing_moves():
    child = _RefdocChild(works_at=None)  # 어느 버튼도 목록을 채우지 못함
    res = await csteps.move_refdoc_down(child, "GW1")
    assert res["ok"] is False and res["verified"] is False
    assert "첨부되지 않았습니다" in res["reason"]


async def test_move_refdoc_down_reports_when_button_not_found():
    child = _RefdocChild(mark_ok=False)
    res = await csteps.move_refdoc_down(child, "GW1")
    assert res["ok"] is False and res["verified"] is False


async def test_run_refdoc_search_uses_element_click_not_coordinates():
    child = _RefdocChild()
    assert await csteps.run_refdoc_search(child) is True
    assert child.element_clicks == ["[data-nb-refdoc='search']"]
    assert child.mouse_clicks == []  # 좌표 클릭 금지


async def test_run_refdoc_search_false_when_button_missing():
    child = _RefdocChild(mark_ok=False)
    assert await csteps.run_refdoc_search(child) is False


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


# ══════════════════════════════════════════════════════════════════════════════
# 반영/도착 확인 계약(2026-07-27) — 확인 커널(nbkit.omnisol.verify) 사용부.
#   Phase B 는 클릭·호출 성공을 성공으로 간주하던 구간이었다: 탭 도착, 결의구분, 조회 결과.
# ══════════════════════════════════════════════════════════════════════════════
async def test_open_collect_tab_requires_screen_anchor_visible():
    # 이 화면에만 있는 조회조건 라벨('결의부서')이 렌더돼야 도착으로 인정한다.
    # ⚠ kendo 가 숨기는 native select 를 앵커로 쓰면 도착해도 항상 실패한다(2026-07-27 실측)
    #   — 앵커는 라벨 리더여야 한다.
    page = _FakePage({js_lib.FIELD_LABEL_VISIBLE_JS: True, js_lib.NOTICE_POPUP_BOXES_JS: None})
    res = await csteps.open_collect_tab(page)
    assert res["ok"] is True
    assert page.eval_args[js_lib.FIELD_LABEL_VISIBLE_JS] == csteps.COLLECT_SCREEN_LABEL
    assert js_lib.VISIBLE_ELEMENT_JS not in page.eval_args  # select 가시성에 의존하지 않는다.


async def test_open_collect_tab_fails_when_tab_did_not_open():
    # ⚠ 회귀 핵심: 종전엔 클릭 후 고정 2초 뒤 무조건 성공 → 전표조회승인 화면을 결의서
    # 화면으로 착각하고 조회조건을 엉뚱한 폼에 넣었다.
    page = _FakePage({js_lib.FIELD_LABEL_VISIBLE_JS: False, js_lib.NOTICE_POPUP_BOXES_JS: None})
    res = await csteps.open_collect_tab(page)
    assert res["ok"] is False and "도착" in res["reason"]


async def test_set_collect_gubun_card_fails_when_selection_reverts():
    # 결의구분이 '카드'로 남지 않으면 False — 호출부(collect_payments)가 조회 없이 중단한다
    # (틀린 결의구분으로 수집한 맵은 전건을 '맵에 없음'으로 건너뛰게 만든다).
    page = _FakePage(
        {
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS: {"ok": True, "val": "52"},
            js_lib.SELECTED_TEXT_JS: {"ok": True, "text": "전체", "value": "0"},
        }
    )
    assert await csteps.set_collect_gubun_card(page) is False


async def test_set_collect_gubun_card_true_when_selection_confirmed():
    page = _FakePage(
        {
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS: {"ok": True, "val": "52"},
            js_lib.SELECTED_TEXT_JS: {"ok": True, "text": "카드", "value": "52"},
        }
    )
    assert await csteps.set_collect_gubun_card(page) is True


async def test_run_collect_query_requires_result_grid_response():
    # 클릭만으로 성공을 단정하지 않는다 — 가시 마스터 그리드가 rowcount 를 낼 수 있어야 한다
    # (0건도 정상: 확인 대상은 '응답 가능 상태'이지 '결과 존재'가 아니다).
    ok_page = _FakePage(
        {cjs.VISIBLE_LOOKUP_BTN_RECT_JS: {"x": 33, "y": 44}, cjs.VISIBLE_MASTER_ROWCOUNT_JS: 0}
    )
    assert await csteps.run_collect_query(ok_page) is True

    stale = _FakePage(
        {cjs.VISIBLE_LOOKUP_BTN_RECT_JS: {"x": 33, "y": 44}, cjs.VISIBLE_MASTER_ROWCOUNT_JS: -1}
    )
    assert await csteps.run_collect_query(stale) is False


async def test_switch_back_to_voucher_tab_requires_approval_button_visible():
    from app.agents.voucher_receivable import js as vr_js

    ok_page = _FakePage({vr_js.APPROVAL_BTN_RECT_JS: {"x": 9, "y": 9}})
    assert await csteps.switch_back_to_voucher_tab(ok_page) is True

    wrong_tab = _FakePage({vr_js.APPROVAL_BTN_RECT_JS: None})
    assert await csteps.switch_back_to_voucher_tab(wrong_tab) is False


async def test_set_collect_period_override_confirms_target_month():
    page = _FakePage(
        {
            cjs.SET_PERIOD_RANGE_JS: True,
            js_lib.PERIOD_VALUE_JS: {"found": True, "ym": ["202602", "202602"], "now": "202607"},
        }
    )
    assert await csteps.set_collect_period(page, "202602") is True

    wrong = _FakePage(
        {
            cjs.SET_PERIOD_RANGE_JS: True,
            js_lib.PERIOD_VALUE_JS: {"found": True, "ym": ["202607", "202607"], "now": "202607"},
        }
    )
    assert await csteps.set_collect_period(wrong, "202602") is False


async def test_open_refdoc_dialog_requires_dialog_title_visible():
    child = _FakeChild(
        {
            cjs.REFDOC_SELECT_BTN_SCROLL_JS: True,
            cjs.REFDOC_SELECT_BTN_RECT_JS: {"x": 1, "y": 2},
            js_lib.VISIBLE_TEXT_JS: True,
        }
    )
    assert await csteps.open_refdoc_dialog(child) is True

    not_open = _FakeChild(
        {
            cjs.REFDOC_SELECT_BTN_SCROLL_JS: True,
            cjs.REFDOC_SELECT_BTN_RECT_JS: {"x": 1, "y": 2},
            js_lib.VISIBLE_TEXT_JS: False,
        }
    )
    assert await csteps.open_refdoc_dialog(not_open) is False


class _RefdocPanel:
    """필터 패널 토글을 **실물 시맨틱**으로 모사 — 누를 때마다 접힘/펼침이 뒤집히고,
    '조회' 버튼은 펼쳐졌을 때만 좌표를 돌려준다."""

    def __init__(self, *, expanded: bool = False, toggle_broken: bool = False) -> None:
        self.expanded = expanded
        self._toggle_broken = toggle_broken
        self.toggle_clicks = 0
        self.clicks: list = []
        self.mouse = _FakeMouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        if js_src == cjs.REFDOC_SEARCH_BTN_RECT_JS:
            return {"x": 492, "y": 256} if self.expanded else None
        return None

    async def click(self, selector, timeout=None):
        assert selector == cjs.REFDOC_FILTER_EXPAND_SELECTOR
        self.toggle_clicks += 1
        if self._toggle_broken:
            raise TimeoutError("toggle not found")
        self.expanded = not self.expanded  # ⚠ 토글 — 이미 펼쳐졌으면 접힌다.

    async def wait_for_timeout(self, ms):
        return None


async def test_expand_refdoc_filter_opens_collapsed_panel():
    child = _RefdocPanel(expanded=False)
    assert await csteps.expand_refdoc_filter(child) is True
    assert child.toggle_clicks == 1 and child.expanded is True


async def test_expand_refdoc_filter_does_not_collapse_already_open_panel():
    # ⚠ 회귀 핵심: 이미 펼쳐진 상태에서 또 누르면 **접혀서** 조회 버튼이 사라진다
    # → run_refdoc_search 가 조용히 아무것도 못 누르는 산발적 증상의 원인이었다.
    child = _RefdocPanel(expanded=True)
    assert await csteps.expand_refdoc_filter(child) is True
    assert child.toggle_clicks == 0 and child.expanded is True


async def test_expand_refdoc_filter_false_when_button_never_appears():
    child = _RefdocPanel(expanded=False, toggle_broken=True)
    assert await csteps.expand_refdoc_filter(child) is False




async def test_select_refdoc_first_row_clicks_checkbox_column():
    """⚠ 실측(2026-07-27): 행 중앙(제목 셀) 클릭은 선택되지 않는다 — **체크박스 열**이어야 한다."""

    class _GridChild:
        def __init__(self, y=319):
            self._y = y
            self.clicks: list = []
            self.mouse = _FakeMouse(self.clicks)

        async def evaluate(self, js_src, arg=None):
            if js_src == cjs.REFDOC_STATE_JS:
                return {"ok": True, "total": 1, "noData": False, "selectedEmpty": True,
                        "topGrid": {"x": 150, "y": self._y, "w": 684, "h": 189},
                        "bottomGrid": {"x": 150, "y": 623, "w": 684, "h": 189}}
            return None

        async def wait_for_timeout(self, ms):
            return None

    child = _GridChild()
    assert await csteps.select_refdoc_first_row(child) is True
    assert child.clicks == [(166, 361)]  # 체크박스 열(+16), 헤더(30) 아래 첫 행 중앙(+12)


async def test_select_refdoc_first_row_refuses_when_grid_offscreen():
    """뷰포트 밖(음수 y) 좌표를 누르면 아무 일도 안 일어나므로 시도하지 않는다."""

    class _OffScreen:
        async def evaluate(self, js_src, arg=None):
            if js_src == cjs.REFDOC_STATE_JS:
                return {"ok": True, "total": 1, "noData": False, "selectedEmpty": True,
                        "topGrid": {"x": 150, "y": -504, "w": 684, "h": 189}, "bottomGrid": None}
            return None

        async def wait_for_timeout(self, ms):
            return None

    assert await csteps.select_refdoc_first_row(_OffScreen()) is False


async def test_move_refdoc_down_requires_count_to_grow():
    """이동 **전에 이미** 다른 문서가 있어도, 우리 문서가 늘어나야 성공이다(귀속 확인)."""
    child = _RefdocChild(works_at=0, doc_no="GW9", pre_docs=("GW1",))
    res = await csteps.move_refdoc_down(child, "GW9")
    assert res["verified"] is True and res["pre_count"] == 1 and res["count"] == 2


async def test_move_refdoc_down_fails_when_target_doc_not_in_list():
    """목록이 늘어도 **대상 문서번호가 아니면** 실패 — 엉뚱한 문서 첨부를 성공으로 치지 않는다."""
    child = _RefdocChild(works_at=0, doc_no="OTHER")
    res = await csteps.move_refdoc_down(child, "GW1")
    assert res["verified"] is False


async def test_selected_list_readers_tri_state():
    """행 수/문서 포함 여부 — 판독 불가(None)를 0건과 구분한다."""

    class _S:
        def __init__(self, grids):
            self._grids = grids

        async def evaluate(self, js_src, arg=None):
            return self._grids if js_src == cjs.REFDOC_GRID_ROWS_JS else None

        async def wait_for_timeout(self, ms):
            return None

    filled = _S({"ok": True, "top": {"count": 1, "docNos": ["GW1"]},
                 "selected": {"count": 1, "docNos": ["GW1"]}})
    empty = _S({"ok": True, "top": {"count": 1, "docNos": ["GW1"]},
                "selected": {"count": 0, "docNos": []}})
    broken = _S({"ok": False, "reason": "grids-not-ready"})

    assert await csteps.selected_list_count(filled) == 1
    assert await csteps.selected_list_count(empty) == 0
    assert await csteps.selected_list_count(broken) is None
    assert await csteps.selected_list_has_doc(filled, "GW1") is True
    assert await csteps.selected_list_has_doc(filled, "GW2") is False
    assert await csteps.selected_list_has_doc(broken, "GW1") is None
