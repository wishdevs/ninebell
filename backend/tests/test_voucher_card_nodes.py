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
        return True

    async def _dept(page):
        calls.append("dept")
        return True

    async def _writer(page):
        calls.append("writer")
        return True

    async def _period(page, ym):
        calls.append(("period", ym))
        return True

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
        {"events": _q(), "page": _StubPage(), "master_rowcount": 4, "accounting_ym": None}
    )
    assert out["payment_map"] == {"RN1": "GW1", "RN2": "GW2"}
    assert out["payment_map_count"] == 2
    assert_keys_declared(VoucherCardState, out)
    # 순서: 탭 열기 → 부서 → 결의자 → 회계일 → 결의구분 → 조회 → 읽기 → 탭복귀.
    assert calls == [
        "open_tab", "dept", "writer", ("period", None), "gubun", "run", "read", "back",
    ]


async def test_collect_passes_accounting_ym_to_period(monkeypatch):
    calls = _patch_collect_ok(monkeypatch)
    node = make_collect_payments_node()
    await node(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 1, "accounting_ym": "202607"}
    )
    assert ("period", "202607") in calls


async def test_collect_tab_back_failure_errors(monkeypatch):
    _patch_collect_ok(monkeypatch, tab_back=False)
    node = make_collect_payments_node()
    out = await node({"events": _q(), "page": _StubPage(), "master_rowcount": 2})
    assert "탭 복귀 실패" in out["error"]
    assert_keys_declared(VoucherCardState, out)


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
    """참조문서 dialog child 스텁 — 각 JS 상수에 시나리오 값을 돌려주고 mouse/keyboard/click 을
    기록한다. 안전 검증: '확인' 좌표 클릭·REFDOC_CONFIRM_BTN_RECT_JS 평가를 그대로 노출한다."""

    def __init__(self, *, matches=None, docno_value="GW1", down_rect=None) -> None:
        self.evaluated: list[str] = []
        self.mouse_clicks: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self.typed: list[str] = []
        self.clicked_selectors: list[str] = []
        self._matches = matches if matches is not None else []
        self._docno_value = docno_value
        self._down_rect = down_rect
        self.mouse = self._Mouse(self)
        self.keyboard = self._Keyboard(self)

    class _Mouse:
        def __init__(self, c) -> None:
            self._c = c

        async def click(self, x, y):
            self._c.mouse_clicks.append((x, y))

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

    async def evaluate(self, js_src, arg=None):
        self.evaluated.append(js_src)
        if js_src == cjs.REFDOC_SELECT_BTN_SCROLL_JS:
            return True
        if js_src == cjs.REFDOC_SELECT_BTN_RECT_JS:
            return {"x": 100, "y": 200}
        if js_src == cjs.REFDOC_DOCNO_INPUT_RECT_JS:
            return {"x": 110, "y": 210}
        if js_src == cjs.REFDOC_DOCNO_VALUE_JS:
            return self._docno_value
        if js_src == cjs.REFDOC_SEARCH_BTN_RECT_JS:
            return {"x": 120, "y": 220}
        if js_src == cjs.REFDOC_MATCHES_JS:
            no_data = None if self._matches else "조회된 데이터가 없습니다"
            return {"docNoMatches": list(self._matches), "noDataText": no_data}
        if js_src == cjs.REFDOC_SELECT_ROW_JS:
            return bool(self._matches)
        if js_src == cjs.REFDOC_DOWN_BTN_RECT_JS:
            return self._down_rect
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
    child = _RefChild(matches=[])  # 0건(현재 테스트 상태)
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("참조문서 미검색" in m and "시스템 승인 대기" in m for m in logs)
    # ⚠ 절대 안전(행위): 확인 좌표 클릭·확인 좌표 평가 없음.
    assert _CONFIRM_COORD not in child.mouse_clicks
    assert cjs.REFDOC_CONFIRM_BTN_RECT_JS not in child.evaluated
    # dialog 는 취소(X) 로 정리(비영속).
    assert cjs.REFDOC_CLOSE_BTN_RECT_JS in child.evaluated


async def test_on_popup_match_selects_and_moves_down_never_confirms():
    hook = make_reference_doc_hook()  # allow_confirm=False(기본)
    child = _RefChild(matches=["GW1"], docno_value="GW1")
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("참조문서 선택·아래버튼 완료" in m for m in logs)
    assert any("가상: 참조문서 확인·상신" in m for m in logs)
    # 아래버튼은 rect 폴백 좌표(477,412)로 클릭됐다(선택목록 이동, 비영속).
    assert (cjs.REFDOC_DOWN_BTN_FALLBACK["x"], cjs.REFDOC_DOWN_BTN_FALLBACK["y"]) in child.mouse_clicks
    # ⚠ 절대 안전(행위): 확인 미클릭·확인 좌표 미평가.
    assert _CONFIRM_COORD not in child.mouse_clicks
    assert cjs.REFDOC_CONFIRM_BTN_RECT_JS not in child.evaluated


async def test_on_popup_uses_keyboard_clear_then_type_for_docno():
    # React controlled input — setValue 오염 방지: End + Backspace 다회 + 키보드 타이핑.
    hook = make_reference_doc_hook()
    child = _RefChild(matches=["GW1"], docno_value="GW1")
    await hook(child, "GW1", _q())
    assert child.keys.count("Backspace") >= csteps.REFDOC_CLEAR_BACKSPACES
    assert "End" in child.keys
    assert child.typed == ["GW1"]


async def test_on_popup_allow_confirm_gate_clicks_confirm():
    # 게이트 개방(allow_confirm=True) 시에만 확인을 클릭한다(승인 이슈 해소 후 전용).
    hook = make_reference_doc_hook(allow_confirm=True)
    child = _RefChild(matches=["GW1"], docno_value="GW1")
    q = _q()
    await hook(child, "GW1", q)
    logs = _logs(_drain(q))
    assert any("참조문서 확인 클릭(allow_confirm=True)" in m for m in logs)
    assert _CONFIRM_COORD in child.mouse_clicks
    assert cjs.REFDOC_CONFIRM_BTN_RECT_JS in child.evaluated


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


async def test_loop_on_popup_none_gwdocu_when_unmapped(monkeypatch):
    child = _LoopChild()
    _patch_loop_for_card(monkeypatch, child, {0: "RN-UNKNOWN"})
    seen: list = []

    async def _on_popup(c, gwdocu_no, events):
        seen.append(gwdocu_no)

    node = make_loop_approvals_node(on_popup=_on_popup)
    out = await node(
        {"events": _q(), "page": object(), "master_rowcount": 1, "max_rows": 1, "payment_map": {}}
    )
    assert out["processed"] == 1
    assert seen == [None]  # 매핑 없으면 None 을 넘겨 훅이 우아하게 처리.


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
