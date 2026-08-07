"""voucher-card 노드/훅 순수 로직 — 브라우저 없이 계약·안전 검증.

- collect_payments: 단락 / 0건 스킵 / 성공(payment_map) / 탭복귀 실패 → error + state 키 선언.
- reference_doc on_popup: 결재번호 없음 / 0건 우아한 로그 / 매치 선택·아래버튼 / allow_confirm 게이트.
- loop_approvals(on_popup=훅): 카드 분기에서 행 ABDOCU_NO→payment_map→GWDOCU_NO 로 훅 호출.
- ⚠ 절대 안전: 참조문서 '확인'·상신 미클릭(정적 소스 스캔 + 행위 검증).
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.agents.voucher_card import js as cjs
from app.agents.voucher_card import steps as csteps
from app.agents.voucher_card.graph import VoucherCardState
from app.agents.voucher_card.nodes import collect_payments as cp_mod
from app.agents.voucher_card.nodes import reference_doc as rd_mod
from app.agents.voucher_card.nodes.collect_payments import make_collect_payments_node
from app.agents.voucher_card.nodes.reference_doc import make_reference_doc_hook
from app.agents.voucher_receivable import js as vjs
from app.agents.voucher_receivable.nodes import approvals
from app.agents.voucher_receivable.nodes.approvals import make_loop_approvals_node
from nbkit.omnisol import js_lib
from tests.support.state_contract import assert_keys_declared

pytestmark = pytest.mark.asyncio


def _q() -> asyncio.Queue:
    return asyncio.Queue()


def _drain(q: asyncio.Queue) -> list[dict]:
    out: list[dict] = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _logs(frames: list[dict]) -> list[str]:
    return [f["log"] for f in frames if "log" in f]


class _StubPage:
    """collect_payments 는 조작을 csteps 로 위임 — page 는 통과값(emit_shot 은 스텁 무시)."""

    async def evaluate(self, js_src, arg=None):
        return True

    async def wait_for_timeout(self, ms):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# collect_payments
# ══════════════════════════════════════════════════════════════════════════════
def _patch_collect_ok(monkeypatch, *, mapping=None, tab_back=True, calls=None):
    calls = calls if calls is not None else []
    mapping = mapping if mapping is not None else {"RN1": "(주)나인벨-2026-1"}

    async def _open_tab(page):
        calls.append("open_tab")
        return {"ok": True}

    async def _dept(page):
        calls.append("dept")
        return True

    async def _writer(page):
        calls.append("writer")
        return {"ok": True}

    async def _period(page, start, end):
        calls.append(("period", start, end))
        return {"ok": True}

    async def _gubun(page):
        calls.append("gubun")
        return True

    async def _run(page):
        calls.append("run")
        return True

    async def _read(page):
        calls.append("read")
        return {"ok": True, "n": len(mapping), "map": dict(mapping)}

    async def _back(page):
        calls.append("back")
        return tab_back

    monkeypatch.setattr(cp_mod.steps, "open_collect_tab", _open_tab)
    monkeypatch.setattr(cp_mod.steps, "set_collect_dept_all", _dept)
    monkeypatch.setattr(cp_mod.steps, "clear_collect_writer", _writer)
    monkeypatch.setattr(cp_mod.steps, "set_collect_period", _period)
    monkeypatch.setattr(cp_mod.steps, "set_collect_gubun_card", _gubun)
    monkeypatch.setattr(cp_mod.steps, "run_collect_query", _run)
    monkeypatch.setattr(cp_mod.steps, "read_payment_map", _read)
    monkeypatch.setattr(cp_mod.steps, "switch_back_to_voucher_tab", _back)
    return calls


async def test_collect_short_circuits_on_prior_error():
    node = make_collect_payments_node()
    out = await node({"events": _q(), "error": "이전 실패", "page": _StubPage()})
    assert out == {}


async def test_collect_zero_rowcount_skips_and_empty_map():
    node = make_collect_payments_node()
    out = await node({"events": _q(), "page": _StubPage(), "master_rowcount": 0})
    assert out == {"payment_map": {}, "payment_map_count": 0}
    assert_keys_declared(VoucherCardState, out)


async def test_collect_success_builds_payment_map(monkeypatch):
    calls = _patch_collect_ok(monkeypatch, mapping={"RN1": "GW1", "RN2": "GW2"})
    node = make_collect_payments_node()
    out = await node(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 4, "period_from": None}
    )
    assert out["payment_map"] == {"RN1": "GW1", "RN2": "GW2"}
    assert out["payment_map_count"] == 2
    assert_keys_declared(VoucherCardState, out)
    # 순서: 탭 열기 → 부서 → 결의자 → 회계일 → 결의구분 → 조회 → 읽기 → 탭복귀.
    assert calls == [
        "open_tab", "dept", "writer", ("period", None, None), "gubun", "run", "read", "back",
    ]


async def test_collect_passes_period_range_to_period(monkeypatch):
    """실행 전 폼이 고른 기간이 결의서조회승인 회계일로 그대로 전달된다(월 부분 기간 포함)."""
    calls = _patch_collect_ok(monkeypatch)
    node = make_collect_payments_node()
    await node(
        {
            "events": _q(),
            "page": _StubPage(),
            "master_rowcount": 1,
            "period_from": "20260701",
            "period_to": "20260705",
        }
    )
    assert ("period", "20260701", "20260705") in calls


async def test_collect_tab_back_failure_errors(monkeypatch):
    _patch_collect_ok(monkeypatch, tab_back=False)
    node = make_collect_payments_node()
    out = await node({"events": _q(), "page": _StubPage(), "master_rowcount": 2})
    assert "탭 복귀 실패" in out["error"]
    assert_keys_declared(VoucherCardState, out)


async def test_collect_no_abdocu_rows_skips_tab_and_ends(monkeypatch):
    """결의서번호(ABDOCU_NO) 보유 0건 — 결의서조회승인 탭을 열지 않고 빈 맵으로 즉시 종료
    (사용자 확정 2026-07-30: 대상이 없으면 다중탭 수집 불필요)."""
    calls = _patch_collect_ok(monkeypatch)

    async def _count(page):
        return {"ok": True, "n": 5, "withAb": 0}

    monkeypatch.setattr(cp_mod.shared_steps, "count_rows_with_abdocu", _count)
    node = make_collect_payments_node()
    out = await node({"events": _q(), "page": _StubPage(), "master_rowcount": 5})
    assert out == {"payment_map": {}, "payment_map_count": 0}
    assert calls == []  # 탭 열기·조건 세팅·조회 전부 미실행.
    assert_keys_declared(VoucherCardState, out)


async def test_collect_abdocu_precheck_failure_falls_back_to_collect(monkeypatch):
    """사전 판정 실패(ok:False)는 즉시 종료하지 않고 기존 경로(수집 진행)로 폴백한다."""
    calls = _patch_collect_ok(monkeypatch)

    async def _count(page):
        return {"ok": False, "reason": "stub"}

    monkeypatch.setattr(cp_mod.shared_steps, "count_rows_with_abdocu", _count)
    node = make_collect_payments_node()
    out = await node({"events": _q(), "page": _StubPage(), "master_rowcount": 2})
    assert "open_tab" in calls and "error" not in out


async def test_collect_grid_unreadable_proceeds_empty(monkeypatch):
    # 그리드 읽기 실패는 error 로 단락하지 않고 빈 맵으로 진행(참조문서 훅이 우아하게 처리).
    _patch_collect_ok(monkeypatch)

    async def _read_fail(page):
        return {"ok": False, "reason": "no-grid", "map": {}}

    monkeypatch.setattr(cp_mod.steps, "read_payment_map", _read_fail)
    node = make_collect_payments_node()
    out = await node({"events": _q(), "page": _StubPage(), "master_rowcount": 2})
    assert out["payment_map"] == {} and out["payment_map_count"] == 0
    assert "error" not in out


# ══════════════════════════════════════════════════════════════════════════════
# reference_doc on_popup 훅 — child(EAP React) 스텁으로 검증
# ══════════════════════════════════════════════════════════════════════════════
class _RefChild:
    """참조문서 dialog child 스텁 — **실물 시맨틱**으로 모사한다(2026-07-27 실측 반영).

    - 목록은 RealGrid **캔버스**라 행이 DOM 에 없다 → 판정은 상태 리더(REFDOC_STATE_JS)의
      total / noData / selectedEmpty 로만 한다.
    - 조회·이동 버튼은 **마커 + 요소 클릭**(data-nb-refdoc) 경로다.
    - 이동 버튼은 두 개 중 하나만 '아래(추가)'다 — `move_works_at` 인덱스를 눌렀을 때만
      선택된 문서 목록이 채워진다(selectedEmpty=False).
    """

    def __init__(
        self,
        *,
        total: int | None = 1,
        total_before: int | None = 2714,
        no_data: bool = False,
        move_works_at: int | None = 0,
        dialog_visible: bool = True,
        docno_value: str = "GW1",
        panel_expanded: bool = True,
        confirm_closes_dialog: bool = True,
    ) -> None:
        # 조회 **전**에는 전체 목록 건수, 조회 후에 필터 결과로 바뀐다(실물 시맨틱).
        self._total_after = total
        self._total = total_before
        self._no_data_after = no_data
        self._no_data = False
        self._move_works_at = move_works_at
        self._dialog_visible = dialog_visible
        self._docno_value = docno_value
        self._panel_expanded = panel_expanded
        self._selected_empty = True
        self._selected_docs: list[str] = []      # 선택된 문서 목록(gridView 로 읽히는 실제 행)
        self._doc_no = docno_value               # 검색 대상 문서번호
        self._marked_index = 0
        self._confirm_closes_dialog = confirm_closes_dialog
        self._dialog_closed = False              # 확인 클릭 적용 시 dialog 소멸(실물 시맨틱)
        self.evaluated: list[str] = []
        self.mouse_clicks: list[tuple[int, int]] = []
        self.element_clicks: list[str] = []
        self.keys: list[str] = []
        self.typed: list[str] = []
        self.clicked_selectors: list[str] = []
        self.mouse = self._Mouse(self)
        self.keyboard = self._Keyboard(self)

    class _Mouse:
        def __init__(self, c) -> None:
            self._c = c

        async def click(self, x, y):
            self._c.mouse_clicks.append((x, y))
            # 확인(130,230) 클릭 → 적용되면 dialog 소멸(click_refdoc_confirm 사후검증 대상).
            if (x, y) == _CONFIRM_COORD and self._c._confirm_closes_dialog:
                self._c._dialog_closed = True

    class _Keyboard:
        def __init__(self, c) -> None:
            self._c = c

        async def press(self, k):
            self._c.keys.append(k)

        async def type(self, t):
            self._c.typed.append(t)

    async def wait_for_timeout(self, ms):
        return None

    async def click(self, selector, timeout=None):
        self.clicked_selectors.append(selector)
        if selector.startswith("[data-nb-refdoc="):
            self.element_clicks.append(selector)
            if "search" in selector:
                # 조회 실행 → 목록이 필터 결과로 갱신된다.
                self._total, self._no_data = self._total_after, self._no_data_after
            if "move" in selector and self._marked_index == self._move_works_at:
                # 올바른 이동 버튼 → 선택 목록에 **그 문서가** 담긴다(실물 시맨틱).
                self._selected_empty = False
                if self._doc_no not in self._selected_docs:
                    self._selected_docs.append(self._doc_no)
        elif selector == cjs.REFDOC_FILTER_EXPAND_SELECTOR:
            self._panel_expanded = not self._panel_expanded  # 토글

    async def evaluate(self, js_src, arg=None):
        self.evaluated.append(js_src)
        if js_src == cjs.REFDOC_SELECT_BTN_SCROLL_JS:
            return True
        if js_src == cjs.REFDOC_SELECT_BTN_RECT_JS:
            return {"x": 100, "y": 200}
        if js_src == js_lib.VISIBLE_TEXT_JS:
            return arg == csteps.REFDOC_DIALOG_TITLE and self._dialog_visible
        if js_src == cjs.REFDOC_SEARCH_BTN_RECT_JS:
            return {"x": 460, "y": 242} if self._panel_expanded else None
        if js_src == cjs.REFDOC_DOCNO_INPUT_RECT_JS:
            return {"x": 110, "y": 210}
        if js_src == cjs.REFDOC_DOCNO_VALUE_JS:
            return self._docno_value
        if js_src == cjs.REFDOC_MARK_JS:
            kind = (arg or {}).get("kind")
            if kind == "search":
                return {"ok": True, "marked": "search"} if self._panel_expanded else {
                    "ok": False, "reason": "no-search-button"}
            self._marked_index = (arg or {}).get("index", 0)
            return {"ok": True, "marked": "move", "count": 2, "index": self._marked_index}
        if js_src == cjs.REFDOC_STATE_JS:
            if self._dialog_closed:
                return {"ok": False, "reason": "no-dialog"}
            return {
                "ok": True,
                "total": self._total,
                "noData": self._no_data,
                "selectedEmpty": self._selected_empty,
                "topGrid": {"x": 150, "y": 319, "w": 684, "h": 189},
                "bottomGrid": {"x": 150, "y": 623, "w": 684, "h": 189},
            }
        if js_src == cjs.REFDOC_TOP_CHECKED_JS:
            # 체크박스 좌표(166,361) 클릭이 실제로 있었을 때만 체크 반영(실물 시맨틱).
            checked = 1 if (166, 361) in self.mouse_clicks else 0
            return {"ok": True, "checked": checked, "api": "getCheckedRows"}
        if js_src == cjs.REFDOC_GRID_ROWS_JS:
            return {
                "ok": True,
                "top": {"count": self._total or 0, "docNos": [self._doc_no] if self._total else []},
                "selected": {"count": len(self._selected_docs), "docNos": list(self._selected_docs)},
            }
        if js_src == cjs.REFDOC_CONFIRM_BTN_RECT_JS:
            return {"x": 130, "y": 230}
        if js_src == cjs.REFDOC_CLOSE_BTN_RECT_JS:
            return {"x": 140, "y": 240}
        raise AssertionError(f"unexpected js: {js_src[:60]!r}")


_CONFIRM_COORD = (130, 230)


async def test_on_popup_no_gwdocu_no_logs_and_skips():
    hook = make_reference_doc_hook()
    child = _RefChild()
    q = _q()
    await hook(child, None, q)
    logs = _logs(_drain(q))
    assert any("결재번호 미상" in m for m in logs)
    # dialog 자체를 열지 않았다(참조문서 선택 스크롤/좌표 평가 없음).
    assert cjs.REFDOC_SELECT_BTN_SCROLL_JS not in child.evaluated
    assert child.mouse_clicks == []


async def test_on_popup_zero_matches_graceful_log_never_confirms():
    hook = make_reference_doc_hook()  # allow_confirm=False
    child = _RefChild(total=0, no_data=True)
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    # 조회를 **실행한 뒤의** 0건임을 로그가 구분해 말한다(조회 미실행과 다른 상황).
    assert any("검색 결과 0건" in m and "조회는 정상 실행됨" in m for m in logs)
    # ⚠ 절대 안전(행위): 확인 좌표 클릭·확인 좌표 평가 없음.
    assert _CONFIRM_COORD not in child.mouse_clicks
    assert cjs.REFDOC_CONFIRM_BTN_RECT_JS not in child.evaluated
    # dialog 는 취소(X) 로 정리(비영속).
    assert cjs.REFDOC_CLOSE_BTN_RECT_JS in child.evaluated


async def test_on_popup_match_selects_and_moves_down_never_confirms():
    hook = make_reference_doc_hook()  # allow_confirm=False(기본)
    child = _RefChild(total=1, docno_value="GW1")
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    # 이동 결과(선택된 문서 목록)를 읽을 리더가 아직 없다 — '완료'가 아니라 '미확인'으로 로그한다.
    assert any("참조문서 첨부 완료" in m and "문서번호 GW1 포함 확인" in m for m in logs)
    assert any("가상: 참조문서 확인·상신" in m for m in logs)
    # 이동은 **요소 클릭**(마커)으로 한다 — 좌표 클릭 금지(2026-07-27 회귀).
    assert "[data-nb-refdoc='move']" in child.element_clicks
    # ⚠ 절대 안전(행위): 확인 미클릭·확인 좌표 미평가.
    assert _CONFIRM_COORD not in child.mouse_clicks
    assert cjs.REFDOC_CONFIRM_BTN_RECT_JS not in child.evaluated


async def test_on_popup_uses_keyboard_clear_then_type_for_docno():
    # React controlled input — setValue 오염 방지: End + Backspace 다회 + 키보드 타이핑.
    hook = make_reference_doc_hook()
    child = _RefChild(total=1, docno_value="GW1")
    await hook(child, "GW1", _q())
    assert child.keys.count("Backspace") >= csteps.REFDOC_CLEAR_BACKSPACES
    assert "End" in child.keys
    assert child.typed == ["GW1"]


async def test_on_popup_allow_confirm_gate_clicks_confirm():
    # 게이트 개방(allow_confirm=True) 시에만 확인을 클릭한다(승인 이슈 해소 후 전용).
    hook = make_reference_doc_hook(allow_confirm=True)
    child = _RefChild(total=1, docno_value="GW1")
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("참조문서 확인 클릭(allow_confirm=True)" in m for m in logs)
    assert _CONFIRM_COORD in child.mouse_clicks
    assert cjs.REFDOC_CONFIRM_BTN_RECT_JS in child.evaluated


async def test_on_popup_allow_confirm_click_failure_warns_and_closes():
    # ⚠ 회귀 핵심(2026-08-07 감사): 종전 훅은 click_refdoc_confirm 반환을 버리고 무조건
    # "확인 클릭" action 로그를 남겼다 — 미적용(다이얼로그 잔존)이 성공처럼 보고됐다.
    # 이제 실패면 warn 으로 분리하고 dialog 를 닫아 정리한다.
    hook = make_reference_doc_hook(allow_confirm=True)
    child = _RefChild(total=1, docno_value="GW1", confirm_closes_dialog=False)
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("참조문서 확인 클릭 실패" in m for m in logs)
    assert not any("참조문서 확인 클릭(allow_confirm=True)" in m for m in logs)
    # dialog 는 취소(X)로 정리한다.
    assert cjs.REFDOC_CLOSE_BTN_RECT_JS in child.evaluated
    assert (140, 240) in child.mouse_clicks


async def test_on_popup_dialog_not_found_logs_and_returns():
    hook = make_reference_doc_hook()

    class _NoBtnChild(_RefChild):
        async def evaluate(self, js_src, arg=None):
            self.evaluated.append(js_src)
            if js_src == cjs.REFDOC_SELECT_BTN_SCROLL_JS:
                return False
            if js_src == cjs.REFDOC_SELECT_BTN_RECT_JS:
                return None  # 참조문서 선택 버튼 못 찾음.
            return await super().evaluate(js_src, arg)

    child = _NoBtnChild()
    q = _q()
    await hook(child, "GW1", q)
    assert any("참조문서 선택 버튼을 찾지 못했" in m for m in _logs(_drain(q)))
    assert child.mouse_clicks == []


# ══════════════════════════════════════════════════════════════════════════════
# loop_approvals(on_popup=훅) — 카드 분기: 행 ABDOCU_NO → payment_map → GWDOCU_NO
# ══════════════════════════════════════════════════════════════════════════════
class _LoopChild:
    """loop_approvals 용 결제창 스텁 — poll_child_ready/read_child_docu_no 를 실구현으로 통과."""

    def __init__(self) -> None:
        self.closed = False

    async def wait_for_load_state(self, *a, **k):
        return None

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.CHILD_DOCU_NO_JS:
            return []  # 후보 0개 = 모호(soft) → mismatch 없음, 정상 진행.
        return [{"text": "상신", "x": 1, "y": 1, "visible": True}]  # 상단버튼(렌더 판정)

    async def close(self):
        self.closed = True


def _patch_loop_for_card(monkeypatch, child, abdocu_by_idx):
    async def _key(page, idx):
        return f"FI{idx:016d}"

    async def _abdocu(page, idx):
        return abdocu_by_idx.get(idx)

    async def _uncheck(page):
        return True

    async def _check(page, idx):
        return True

    async def _open(page):
        return child

    monkeypatch.setattr(approvals.steps, "read_row_key", _key)
    monkeypatch.setattr(approvals.steps, "read_row_abdocu_no", _abdocu)
    monkeypatch.setattr(approvals.steps, "uncheck_all_rows", _uncheck)
    monkeypatch.setattr(approvals.steps, "check_row", _check)
    monkeypatch.setattr(approvals.steps, "open_approval", _open)


async def test_loop_on_popup_receives_mapped_gwdocu(monkeypatch):
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "RN-A", 1: "RN-B"})
    seen: list = []

    async def _on_popup(c, gwdocu_no, events):
        assert c is child
        seen.append(gwdocu_no)

    node = make_loop_approvals_node(on_popup=_on_popup)
    state = {
        "events": _q(),
        "page": object(),
        "master_rowcount": 2,
        "max_rows": 2,
        "payment_map": {"RN-A": "GW-A", "RN-B": "GW-B"},
    }
    out = await node(state)
    assert out["processed"] == 2
    # 각 행의 ABDOCU_NO(RN-A/RN-B) → payment_map → GWDOCU_NO(GW-A/GW-B) 로 훅 호출.
    assert seen == ["GW-A", "GW-B"]


async def test_loop_summary_aggregates_refdoc_outcomes(monkeypatch):
    """훅이 반환한 참조문서 결과가 최종 요약에 집계된다 — 누락이 요약에서 보이게(2026-08-06).

    종전에는 요약이 "N건 중 N건 결제창 확인"만 말해 참조문서 미첨부가 중간 warn 한 줄로
    스쳐 지나갔다(사용자가 "너무 빨라서 안 보였다"고 한 보고 갭).
    """
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "RN-A", 1: "RN-B"})
    outcomes = {"GW-A": "첨부", "GW-B": "창 열기 실패(클릭 후 미개방)"}

    async def _on_popup(c, gwdocu_no, events):
        return outcomes[gwdocu_no]

    node = make_loop_approvals_node(on_popup=_on_popup)
    out = await node(
        {
            "events": _q(),
            "page": object(),
            "master_rowcount": 2,
            "max_rows": 2,
            "payment_map": {"RN-A": "GW-A", "RN-B": "GW-B"},
        }
    )
    assert "참조문서 첨부 1건" in out["result"]
    assert "미첨부 1건" in out["result"]
    assert "창 열기 실패(클릭 후 미개방)" in out["result"]  # 전표별 사유까지 요약에 남는다.


async def test_loop_skips_row_without_gwdocu_mapping(monkeypatch):
    # 카드: 결의서번호(ABDOCU_NO)가 payment_map 에 없으면(직접 전표 등) 결제창을 안 열고 건너뛴다.
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "RN-UNKNOWN"})
    seen: list = []

    async def _on_popup(c, gwdocu_no, events):
        seen.append(gwdocu_no)

    node = make_loop_approvals_node(on_popup=_on_popup)
    out = await node(
        {"events": _q(), "page": object(), "master_rowcount": 1, "max_rows": 1, "payment_map": {}}
    )
    assert out["processed"] == 0  # 매핑 없는 행은 건너뜀(결제창 미오픈)
    assert seen == []  # 훅도 호출되지 않음


async def test_loop_processes_only_rows_with_gwdocu(monkeypatch):
    # 사용자 시나리오(2026-07-21): 결의서번호 있는 행만 처리, 없는 행은 건너뜀.
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "RN-A", 1: "RN-NONE", 2: "RN-B"})
    seen: list = []

    async def _on_popup(c, gwdocu_no, events):
        seen.append(gwdocu_no)

    node = make_loop_approvals_node(on_popup=_on_popup)
    out = await node(
        {
            "events": _q(),
            "page": object(),
            "master_rowcount": 3,
            "max_rows": 3,
            "payment_map": {"RN-A": "GW-A", "RN-B": "GW-B"},  # RN-NONE 은 미수집
        }
    )
    assert out["processed"] == 2  # 3건 중 결의서번호 있는 2건만
    assert seen == ["GW-A", "GW-B"]  # 건너뛴 행엔 훅 미호출


async def test_loop_skip_reason_distinguishes_direct_vs_unmapped(monkeypatch):
    # 2026-07-24 진단: 결의서번호가 아예 없는 직접 전표(row0)와, 결의서번호는 있으나 결재번호
    # 맵에 없는 행(row1)을 구분해 로깅한다(종전엔 둘 다 "결의서번호 없음"으로 뭉뚱그려 원인
    # 파악 불가 — 사용자 리포트). 맵 규모(0건)도 순회 전에 노출한다.
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: None, 1: "RN-X"})

    async def _noop(c, gwdocu_no, events):
        pass

    node = make_loop_approvals_node(on_popup=_noop)
    q = _q()
    out = await node(
        {"events": q, "page": object(), "master_rowcount": 2, "max_rows": 2, "payment_map": {}}
    )
    assert out["processed"] == 0
    joined = "\n".join(_logs(_drain(q)))
    assert "직접 전표" in joined  # row0: 결의서번호 자체가 없음
    assert "맵에 없음" in joined  # row1: 결의서번호는 있으나 맵 미매칭
    assert "맵 0건" in joined  # 맵 규모 노출(왜 0건 처리인지)


async def test_loop_matches_abdocu_with_surrounding_whitespace(monkeypatch):
    # 그리드 표기값에 앞뒤 공백이 섞여도(예 '  RN-A  ') 맵 키와 매칭돼 처리된다(정규화).
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "  RN-A  "})
    seen: list = []

    async def _on_popup(c, gwdocu_no, events):
        seen.append(gwdocu_no)

    node = make_loop_approvals_node(on_popup=_on_popup)
    out = await node(
        {"events": _q(), "page": object(), "master_rowcount": 1, "max_rows": 1,
         "payment_map": {"RN-A": "GW-A"}}
    )
    assert out["processed"] == 1
    assert seen == ["GW-A"]


async def test_loop_on_popup_exception_does_not_abort_batch(monkeypatch):
    # 참조문서 훅이 예외를 던져도 배치는 계속 진행(비크리티컬 — 경고 로그 후 가상 상신).
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "RN-A"})

    async def _boom(c, gwdocu_no, events):
        raise RuntimeError("refdoc boom")

    node = make_loop_approvals_node(on_popup=_boom)
    q = _q()
    out = await node(
        {"events": q, "page": object(), "master_rowcount": 1, "max_rows": 1, "payment_map": {"RN-A": "GW-A"}}
    )
    assert out["processed"] == 1  # 훅 예외에도 가상 상신은 진행.
    assert any("참조문서 처리 중 경고" in m for m in _logs(_drain(q)))


async def test_loop_without_on_popup_never_reads_abdocu(monkeypatch):
    # on_popup=None(매출/매입)은 read_row_abdocu_no 를 호출하지 않는다(공유 백본 무영향).
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "RN-A"})
    called = {"abdocu": 0}

    async def _abdocu(page, idx):
        called["abdocu"] += 1
        return "RN-A"

    monkeypatch.setattr(approvals.steps, "read_row_abdocu_no", _abdocu)
    node = make_loop_approvals_node()  # on_popup 없음
    out = await node({"events": _q(), "page": object(), "master_rowcount": 1, "max_rows": 1})
    assert out["processed"] == 1
    assert called["abdocu"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# ⚠ 절대 안전 — 정적 소스 스캔
# ══════════════════════════════════════════════════════════════════════════════
async def test_reference_doc_confirm_is_gated_by_allow_confirm():
    src = inspect.getsource(rd_mod)
    # 확인 클릭은 반드시 allow_confirm 게이트 뒤에만 있다.
    assert "if allow_confirm:" in src
    gate_pos = src.index("if allow_confirm:")
    confirm_pos = src.index("click_refdoc_confirm")
    assert confirm_pos > gate_pos, "click_refdoc_confirm 은 allow_confirm 게이트 뒤여야 한다"
    # 확인 호출은 소스 전체에서 정확히 1회(게이트 안)만.
    assert src.count("click_refdoc_confirm") == 1


async def test_default_hook_factory_gate_is_closed():
    # 그래프가 쓰는 기본 훅은 allow_confirm=False(미클릭).
    sig = inspect.signature(make_reference_doc_hook)
    assert sig.parameters["allow_confirm"].default is False
    # 그래프 조립부가 명시적으로 allow_confirm=False 로 훅을 생성한다.
    import app.agents.voucher_card.graph as cgraph

    assert "make_reference_doc_hook(allow_confirm=False)" in inspect.getsource(cgraph)


async def test_card_sources_have_no_submit_button_click():
    # 카드 js/steps/훅 어디에도 결제창 '상신' 버튼을 **innerText 로 찾아 클릭**하는 코드가 없다
    # (안전 문구/로그의 '상신' 언급은 제외 — 위험한 건 버튼 텍스트 매치 패턴이다).
    bad_patterns = ["=== '상신'", '=== "상신"', ".includes('상신')", '.includes("상신")']
    for mod in (cjs, csteps, rd_mod):
        src = inspect.getsource(mod)
        for pat in bad_patterns:
            assert pat not in src, f"{mod.__name__} 에 상신 버튼 탐색 패턴 발견: {pat}"


# ══════════════════════════════════════════════════════════════════════════════
# collect_payments 확인 정책(2026-07-27)
#   화면 도착·결의구분·조회 결과 = 하드 실패(잘못된 맵 수집 차단).
#   결의부서·결의자·회계일 = 보조 조건이라 확인 실패해도 warn 후 진행.
# ══════════════════════════════════════════════════════════════════════════════
async def test_collect_stops_when_tab_arrival_unconfirmed(monkeypatch):
    _patch_collect_ok(monkeypatch)

    async def _open_fail(page):
        return {"ok": False, "reason": "결의서조회승인 탭 도착을 확인하지 못했습니다(…)."}

    monkeypatch.setattr(cp_mod.steps, "open_collect_tab", _open_fail)
    out = await make_collect_payments_node()(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 3}
    )
    assert "도착" in out["error"]


async def test_collect_stops_when_gubun_unconfirmed(monkeypatch):
    # ⚠ 카드가 아닌 결의구분으로 수집하면 맵 전체가 어긋나 전건이 '맵에 없음'으로 건너뛰어진다.
    calls = _patch_collect_ok(monkeypatch)

    async def _gubun_fail(page):
        calls.append("gubun")
        return False

    monkeypatch.setattr(cp_mod.steps, "set_collect_gubun_card", _gubun_fail)
    out = await make_collect_payments_node()(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 3}
    )
    assert "결의구분" in out["error"]
    assert "run" not in calls  # 조회 자체를 하지 않는다.


async def test_collect_stops_when_query_result_unconfirmed(monkeypatch):
    calls = _patch_collect_ok(monkeypatch)

    async def _run_fail(page):
        calls.append("run")
        return False

    monkeypatch.setattr(cp_mod.steps, "run_collect_query", _run_fail)
    out = await make_collect_payments_node()(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 3}
    )
    assert "조회 결과" in out["error"]
    assert "read" not in calls  # 스테일 그리드를 맵으로 읽지 않는다.


async def test_collect_writer_clear_failure_is_hard(monkeypatch):
    """⚠ 격상(2026-08-07 사용자 확정): 결의자 비움 실패는 warn 진행이 아니라 **런 중단**이다 —
    로그인 계정으로 좁혀진 채 수집된 맵은 대상과 어긋나 하류가 전 행을 조용히 건너뛴다
    (결의부서와 동일 메커니즘)."""
    calls = _patch_collect_ok(monkeypatch, mapping={"RN1": "GW1"})

    async def _writer_fail(page):
        return {"ok": False, "reason": "'결의자' 비움 확인 실패(재클리어 소진)"}

    monkeypatch.setattr(cp_mod.steps, "clear_collect_writer", _writer_fail)
    out = await make_collect_payments_node()(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 3}
    )
    assert "결의자" in out["error"] and "중단" in out["error"]
    assert "read" not in calls  # 좁혀진 범위로 수집(맵 읽기)하지 않는다.


async def test_collect_period_failure_is_hard(monkeypatch):
    """⚠ 격상(2026-08-07): 회계일 미반영도 하드 — 두 화면 기간이 어긋난 맵은 누락을 만든다."""
    calls = _patch_collect_ok(monkeypatch, mapping={"RN1": "GW1"})

    async def _period_fail(page, start, end):
        return {"ok": False, "reason": "회계일 확인 실패(재세팅 소진)"}

    monkeypatch.setattr(cp_mod.steps, "set_collect_period", _period_fail)
    out = await make_collect_payments_node()(
        {
            "events": _q(),
            "page": _StubPage(),
            "master_rowcount": 3,
            "period_from": "20260701",
            "period_to": "20260705",
        }
    )
    assert "회계일" in out["error"] and "중단" in out["error"]
    assert "read" not in calls


async def test_collect_reader_unknown_warns_but_proceeds(monkeypatch):
    """리더 확인 불가(unknown)는 격상 대상이 아니다 — warn 을 남기고 진행한다(오탐이 런을
    끊지 않게, '정해진 단계를 벗어났을 때만 에러' 규율)."""
    calls = _patch_collect_ok(monkeypatch, mapping={"RN1": "GW1"})

    async def _writer_unknown(page):
        return {"ok": True, "warn": "'결의자' 비움 확인 불가(라벨 미발견)"}

    monkeypatch.setattr(cp_mod.steps, "clear_collect_writer", _writer_unknown)
    q = _q()
    out = await make_collect_payments_node()(
        {"events": q, "page": _StubPage(), "master_rowcount": 3}
    )
    assert out["payment_map"] == {"RN1": "GW1"} and "error" not in out
    assert any("결의자" in m for m in _logs(_drain(q)))
    assert "read" in calls


# ── 참조문서 훅: '조회 미실행' 과 '조회했으나 0건' 을 구분한다(2026-07-27) ──────────
async def test_on_popup_warns_on_panel_uncertainty_but_still_fills_and_searches(monkeypatch):
    """⚠ 회귀 방지(2026-07-27): 패널 확장 '확인 실패'로 **작업을 중단하면 안 된다**.

    한때 이걸 조기 반환 게이트로 만들었더니 문서번호조차 입력되지 않는 더 나쁜 상태가 됐다
    (사용자 리포트). 확인은 진단 정보일 뿐 — 할 수 있는 일(입력·조회)은 그대로 시도한다.
    """
    hook = make_reference_doc_hook()
    child = _RefChild(total=0, no_data=True)

    async def _no_panel(c):
        return False  # 패널 확장을 확인하지 못함(그래도 진행해야 한다)

    monkeypatch.setattr(rd_mod.steps, "expand_refdoc_filter", _no_panel)
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("패널 확장을 확인하지 못했" in m and "그대로 시도" in m for m in logs)
    # 문서번호 입력과 조회 시도가 **여전히** 일어난다.
    assert child.typed == ["GW1"]
    assert cjs.REFDOC_MARK_JS in child.evaluated  # 조회 시도가 실제로 일어났다


async def test_on_popup_reports_search_click_failure_distinctly(monkeypatch):
    hook = make_reference_doc_hook()
    child = _RefChild(total=0, no_data=True)

    async def _ok(c):
        return True

    async def _click_fail(c):
        return False  # 버튼 미가시 등으로 조회를 못 누름

    monkeypatch.setattr(rd_mod.steps, "expand_refdoc_filter", _ok)
    monkeypatch.setattr(rd_mod.steps, "run_refdoc_search", _click_fail)
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("'조회' 버튼을 누르지 못했" in m and "검색 미실행" in m for m in logs)


async def test_on_popup_zero_results_says_search_ran(monkeypatch):
    # 조회는 정상 실행됐고 결과가 0건 — 자동화 실패가 아니라 데이터 상태임을 로그로 구분한다.
    hook = make_reference_doc_hook()
    child = _RefChild(total=0, no_data=True)
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("검색 결과 0건" in m and "조회는 정상 실행됨" in m for m in logs)


# ══════════════════════════════════════════════════════════════════════════════
# 진행률 분모 = **처리 대상 건수**(사용자 리포트 2026-07-27)
#   "전체 19건 중 결의서번호가 있는 건은 4건이라 4건의 진행률을 보여줘야 합니다."
# ══════════════════════════════════════════════════════════════════════════════
def _progress(frames: list[dict]) -> list[dict]:
    return [f["progress"] for f in frames if isinstance(f, dict) and f.get("progress")]


class _RowsPage:
    """마스터 그리드 스텁 — 행별 DOCU_NO / ABDOCU_NO 를 시나리오로 돌려준다."""

    def __init__(self, rows: list[tuple[str, str | None]]) -> None:
        self._rows = rows  # [(DOCU_NO, ABDOCU_NO|None)]

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.READ_ROW_KEY_JS:
            return self._rows[arg][0]
        if js_src == vjs.READ_ROW_ABDOCU_NO_JS:
            return self._rows[arg][1]
        if js_src == vjs.CHECKED_ROW_INDEXES_JS:
            return {"ok": True, "rows": [0]}
        if js_src == vjs.APPROVAL_BTN_RECT_JS:
            return {"x": 1, "y": 1}
        return True

    async def wait_for_timeout(self, ms):
        return None


def _patch_loop_open(monkeypatch, opened: list):
    async def _open(page, **kw):
        opened.append(1)
        return _LoopChild()

    async def _settle(page, child):
        return None

    monkeypatch.setattr(approvals.steps, "open_approval", _open)
    monkeypatch.setattr(approvals.steps, "settle_parent_after_child_close", _settle)


async def test_progress_total_counts_only_eligible_rows(monkeypatch):
    # 조회 19건 중 결의서번호가 맵에 있는 4건만 대상 → 진행률 분모는 4.
    rows = [(f"FI{i:04d}", f"RN{i}" if i < 4 else None) for i in range(19)]
    payment_map = {f"RN{i}": f"GW{i}" for i in range(4)}
    opened: list = []
    _patch_loop_open(monkeypatch, opened)

    seen: list = []

    async def _hook(child, gwdocu_no, events):
        seen.append(gwdocu_no)

    q = _q()
    out = await make_loop_approvals_node(on_popup=_hook)(
        {
            "events": q,
            "page": _RowsPage(rows),
            "master_rowcount": 19,
            "payment_map": payment_map,
        }
    )
    assert out["processed"] == 4
    frames = _drain(q)
    totals = {p["total"] for p in _progress(frames)}
    assert totals == {4}, f"진행률 분모가 대상 건수(4)가 아님: {totals}"
    assert _progress(frames)[-1] == {"done": 4, "total": 4}
    # 결제창은 대상 4건에만 열린다(제외 15건은 열지 않는다).
    assert len(opened) == 4
    assert seen == ["GW0", "GW1", "GW2", "GW3"]


async def test_excluded_rows_are_summarized_not_listed_per_row(monkeypatch):
    # 제외분은 행마다 한 줄씩 찍지 않고 **요약 한 줄**로만 남긴다(화면이 묻히지 않게).
    rows = [(f"FI{i:04d}", f"RN{i}" if i < 2 else None) for i in range(19)]
    _patch_loop_open(monkeypatch, [])

    async def _hook(child, gwdocu_no, events):
        return None

    q = _q()
    await make_loop_approvals_node(on_popup=_hook)(
        {"events": q, "page": _RowsPage(rows), "master_rowcount": 19,
         "payment_map": {"RN0": "GW0", "RN1": "GW1"}}
    )
    logs = _logs(_drain(q))
    assert any("결재 대상 2건" in m for m in logs)
    # 제외 요약은 순회 전 **한 줄**만(완료 요약줄에 다시 언급되는 건 별개다).
    assert sum(1 for m in logs if m.startswith("결재 대상 제외")) == 1
    assert not any("건너뜀(전표" in m for m in logs)  # 행별 나열 없음


async def test_no_eligible_rows_completes_without_opening_approval(monkeypatch):
    rows = [(f"FI{i:04d}", None) for i in range(19)]
    opened: list = []
    _patch_loop_open(monkeypatch, opened)

    async def _hook(child, gwdocu_no, events):
        return None

    q = _q()
    out = await make_loop_approvals_node(on_popup=_hook)(
        {"events": q, "page": _RowsPage(rows), "master_rowcount": 19, "payment_map": {}}
    )
    assert out["processed"] == 0 and opened == []
    assert "결재 대상이 없어" in out["result"]


async def test_max_rows_limits_eligible_targets_not_scanned_rows(monkeypatch):
    # max_rows 는 **대상** 기준으로 자른다(제외분이 상한을 잡아먹지 않게).
    rows = [(f"FI{i:04d}", f"RN{i}" if i >= 15 else None) for i in range(19)]
    opened: list = []
    _patch_loop_open(monkeypatch, opened)

    async def _hook(child, gwdocu_no, events):
        return None

    q = _q()
    out = await make_loop_approvals_node(on_popup=_hook)(
        {"events": q, "page": _RowsPage(rows), "master_rowcount": 19, "max_rows": 2,
         "payment_map": {f"RN{i}": f"GW{i}" for i in range(15, 19)}}
    )
    assert out["processed"] == 2 and len(opened) == 2
    assert {p["total"] for p in _progress(_drain(q))} == {2}


async def test_collect_hard_fails_when_dept_all_unconfirmed(monkeypatch):
    """⚠ 결의부서는 **수집 대상을 정의**한다(2026-07-27 라이브 규명).

    전체선택이 안 되면 로그인 부서로 좁혀져, 전표 행들의 결의서번호와 하나도 겹치지 않는 맵이
    만들어지고 전 행이 건너뛰어진다 — 조용히 진행하면 '아무것도 안 하는' 런이 된다.
    """
    calls = _patch_collect_ok(monkeypatch)

    async def _dept_fail(page):
        return False

    monkeypatch.setattr(cp_mod.steps, "set_collect_dept_all", _dept_fail)
    out = await make_collect_payments_node()(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 3}
    )
    assert "결의부서" in out["error"]
    assert "run" not in calls and "read" not in calls  # 조회·수집으로 진행하지 않는다.


# ══════════════════════════════════════════════════════════════════════════════
# 조회 결과 갱신 판정(2026-07-27 사용자 리포트: "4건 중 3건이 조회만 하고 종료")
#   원인: 기준선을 조회 **후**에 읽고 '총계가 있으면 완료'로 판정 → 필터 반영 전 값(2714)을
#   결과로 오독 → total>1 게이트가 "대상 특정 불가"로 조기 종료 → 이동은 한 건도 실행 안 됨.
# ══════════════════════════════════════════════════════════════════════════════
async def test_on_popup_waits_for_filtered_result_then_moves():
    """조회 전 2714 → 조회 후 1건으로 **갱신될 때까지** 기다린 뒤 선택·이동까지 간다."""
    hook = make_reference_doc_hook()
    child = _RefChild(total_before=2714, total=1)
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("검색 1건 확인" in m for m in logs)
    assert any("참조문서 첨부 완료" in m and "문서번호 GW1 포함 확인" in m for m in logs)
    # 선택된 문서 목록에 실제로 담겼다.
    grids = await child.evaluate(cjs.REFDOC_GRID_ROWS_JS)
    assert grids["selected"]["count"] == 1 and grids["selected"]["docNos"] == ["GW1"]


async def test_on_popup_does_not_move_when_result_stays_unfiltered():
    """조회해도 목록이 그대로면(필터 미반영) **선택·이동하지 않는다** — 엉뚱한 문서 첨부 방지."""
    hook = make_reference_doc_hook()
    child = _RefChild(total_before=2714, total=2714)  # 갱신 없음
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("확인하지 못했" in m or "특정할 수 없어" in m for m in logs)
    grids = await child.evaluate(cjs.REFDOC_GRID_ROWS_JS)
    assert grids["selected"]["count"] == 0  # 아무것도 담기지 않았다.


async def test_on_popup_search_retries_after_realigning_dialog(monkeypatch):
    """조회 클릭이 한 번 실패해도 dialog 재정렬 후 재시도한다(조회조차 못 한 건 방어)."""
    hook = make_reference_doc_hook()
    child = _RefChild(total_before=2714, total=1)
    calls = {"n": 0}
    real_mark = child.evaluate

    async def flaky(js_src, arg=None):
        if js_src == cjs.REFDOC_MARK_JS and (arg or {}).get("kind") == "search":
            calls["n"] += 1
            if calls["n"] == 1:
                return {"ok": False, "reason": "no-search-button"}  # 첫 시도 실패
        return await real_mark(js_src, arg)

    monkeypatch.setattr(child, "evaluate", flaky)
    q = _q()
    await hook(child, "GW1", q)
    assert calls["n"] >= 2  # 재시도했다
    assert any("참조문서 첨부 완료" in m for m in _logs(_drain(q)))


async def test_move_verification_claims_only_what_it_checked():
    """⚠ 검증 범위 정직성: 하단 목록은 캔버스라 **문서번호 대조가 불가능**하다.

    확인한 것은 '목록이 비어있지 않게 됨'까지이므로 로그도 그렇게만 말해야 한다
    (대신 조회 1건 게이트가 어떤 문서인지를 논리적으로 보증한다).
    """
    hook = make_reference_doc_hook()
    child = _RefChild(total_before=2714, total=1)
    q = _q()
    await hook(child, "GW1", q)
    msg = next(m for m in _logs(_drain(q)) if "참조문서 첨부 완료" in m)
    # 이제 **행 수와 문서번호를 실제로** 읽어 확인한다(gridView) — 로그도 그대로 말한다.
    assert "선택된 문서 목록 1건" in msg
    assert "문서번호 GW1 포함 확인" in msg


async def test_on_popup_fails_when_selected_list_ends_up_empty(monkeypatch):
    """⚠ 성공 조건(사용자 확정 2026-08-07): 처음 결제창(0건)과 달리 **선택된 문서 목록이
    정확히 1건(pre+1)** 이고 그 문서가 담겨 있어야 한다.

    이동 직후엔 담겼다고 보고돼도 dialog 를 닫기 직전 최종 확인이 어긋나면 **fatal**(런 중단)
    이다 — 담겼다고 믿고 넘어가면 참조문서 없는 결재가 조용히 진행된다(격상 2026-08-07).
    """
    hook = make_reference_doc_hook()
    child = _RefChild(total_before=2714, total=1)

    async def _moved_then_lost(c, docu_no=None):
        return {"ok": True, "verified": True, "count": 1, "pre_count": 0}

    async def _final_count_zero(c):
        return 0

    async def _final_missing(c, docu_no):
        return False  # 최종 확인에서 목록에 없음

    monkeypatch.setattr(rd_mod.steps, "move_refdoc_down", _moved_then_lost)
    monkeypatch.setattr(rd_mod.steps, "selected_list_count", _final_count_zero)
    monkeypatch.setattr(rd_mod.steps, "selected_list_has_doc", _final_missing)
    q = _q()
    res = await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("최종 확인이 어긋납니다" in m for m in logs)
    assert any("참조문서 첨부 실패" in m for m in logs)
    assert not any("첨부 완료" in m for m in logs)
    assert isinstance(res, dict) and res.get("fatal") is True  # 격상 — 런 중단 신호.
    assert "첨부 실패" in res.get("outcome", "")


async def test_on_popup_select_fail_after_match_is_fatal(monkeypatch):
    """⚠ 격상(2026-08-07): 검색이 대상 1건을 **특정한 뒤의** 행 선택 실패는 warn 진행이 아니라
    fatal — '첨부가 잘 안 되는' 상태가 가상 상신 성공으로 묻히지 않는다."""
    hook = make_reference_doc_hook()
    child = _RefChild(total_before=2714, total=1)

    async def _select_fail(c):
        return False

    monkeypatch.setattr(rd_mod.steps, "select_refdoc_first_row", _select_fail)
    q = _q()
    res = await hook(child, "GW1", q)
    assert isinstance(res, dict) and res.get("fatal") is True
    assert "행 선택" in res.get("reason", "")
    assert cjs.REFDOC_CLOSE_BTN_RECT_JS in child.evaluated  # 실패 정리로 dialog 닫음.


async def test_on_popup_environment_paths_stay_graceful():
    """격상 범위 확인 — 데이터/환경 사정(결재번호 미상·검색 0건)은 종전대로 str 우아 경로다."""
    hook = make_reference_doc_hook()
    assert await hook(_RefChild(), None, _q()) == "결재번호 미상"
    res = await hook(_RefChild(total=0, no_data=True), "GW1", _q())
    assert res == "검색 0건"  # fatal 아님 — 가상 상신으로 진행하는 기존 계약 유지.


async def test_loop_refdoc_fatal_outcome_stops_run(monkeypatch):
    """⚠ 격상 배선(2026-08-07): 훅이 {fatal:True} 를 반환하면 그 전표를 '가상 상신 완료'로
    처리하지 않고 런을 중단한다(결제창 정리는 finally 가 보장)."""
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "RN-A"})

    async def _on_popup(c, gwdocu_no, events):
        return {"outcome": "첨부 실패", "fatal": True,
                "reason": f"참조문서 첨부 실패({gwdocu_no}) — 이동 미성립"}

    node = make_loop_approvals_node(on_popup=_on_popup)
    q = _q()
    out = await node(
        {"events": q, "page": object(), "master_rowcount": 1, "max_rows": 1,
         "payment_map": {"RN-A": "GW-A"}}
    )
    assert "error" in out and "참조문서 첨부 실패" in out["error"]
    logs = _logs(_drain(q))
    assert not any("가상 상신 완료" in m for m in logs)  # 실패 전표를 성공으로 세지 않는다.
