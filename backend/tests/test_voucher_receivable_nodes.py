"""voucher-receivable 노드 순수 로직 테스트 — 브라우저 없이(스텝 monkeypatch) 계약·안전 검증.

- state-contract: 각 노드 출력 키가 VoucherReceivableState 에 선언됐는지(LangGraph silent drop 방지).
- validate_params: 정규화 성공 / 배치 게이트 오류 / 단락.
- set_query·run_query: 성공/실패 분기, master_rowcount 전달.
- loop_approvals: 0건 완료 / 단일행 / max_rows 제한 / 배치 / 실패 분기 +
  ⚠ 절대 안전 가드: 결제창에서 상신·보관을 절대 클릭하지 않는다(정적 소스 스캔 + 행위 검증) +
  가상 상신 로그가 DOCU_NO 를 남긴다.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.agents.voucher_receivable import js as vjs
from app.agents.voucher_receivable import steps as vsteps
from app.agents.voucher_receivable.graph import VoucherReceivableState
from app.agents.voucher_receivable.nodes import approvals, query, validate
from app.agents.voucher_receivable.nodes.approvals import make_loop_approvals_node
from app.agents.voucher_receivable.nodes.query import make_run_query_node, make_set_query_node
from app.agents.voucher_receivable.nodes.validate import make_validate_params_node
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


# ── validate_params ───────────────────────────────────────────────────────────
async def test_validate_default_all_declares_keys():
    node = make_validate_params_node()
    out = await node({"events": _q(), "params": {}})
    assert out == {"max_rows": None}  # 전체(사용자 결정 2026-07-21)
    assert_keys_declared(VoucherReceivableState, out)


async def test_validate_explicit_max_rows():
    node = make_validate_params_node()
    out = await node({"events": _q(), "params": {"max_rows": 4}})
    assert out == {"max_rows": 4}  # 게이트 없음 — 명시값 그대로
    assert_keys_declared(VoucherReceivableState, out)


async def test_validate_invalid_max_rows_errors():
    node = make_validate_params_node()
    out = await node({"events": _q(), "params": {"max_rows": 0}})
    assert "올바르지 않" in out["error"]
    assert_keys_declared(VoucherReceivableState, out)


async def test_validate_short_circuits_on_prior_error():
    node = make_validate_params_node()
    out = await node({"events": _q(), "error": "이전 실패", "params": {}})
    assert out == {}


# ── set_query(스텝 monkeypatch) ───────────────────────────────────────────────
class _FakePage:
    """set_query/run_query 는 조작을 steps 로 위임(스텁) — page 는 통과값일 뿐."""

    async def evaluate(self, js_src, arg=None):
        return True

    async def wait_for_timeout(self, ms):
        return None


def _patch_set_query_ok(monkeypatch, calls: list):
    def _rec(name, ret=None):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, **(ret or {})}

        return _f

    async def _expand(page):
        calls.append("expand")
        return True

    monkeypatch.setattr(query.steps, "expand_condition_panel", _expand)
    monkeypatch.setattr(query.steps, "set_dept_all", _rec("dept", {"n": 46}))
    monkeypatch.setattr(query.steps, "set_period_this_month", _rec("period"))
    monkeypatch.setattr(query.steps, "clear_writer", _rec("writer"))
    monkeypatch.setattr(query.steps, "set_docu_status", _rec("status"))
    monkeypatch.setattr(query.steps, "set_gwaprvlst", _rec("gwaprvlst"))
    monkeypatch.setattr(query.steps, "set_docu_types", _rec("docutypes"))


async def test_set_query_success_order(monkeypatch):
    calls: list = []
    _patch_set_query_ok(monkeypatch, calls)
    out = await make_set_query_node()({"events": _q(), "page": _FakePage()})
    assert out == {}
    assert_keys_declared(VoucherReceivableState, out)
    # 순서: 패널 확장 → 부서 → 회계일 → 작성자 → 전표상태 → 전자결재상태 → 전표유형.
    assert calls == ["expand", "dept", "period", "writer", "status", "gwaprvlst", "docutypes"]


async def test_set_query_field_failure_errors(monkeypatch):
    calls: list = []
    _patch_set_query_ok(monkeypatch, calls)

    async def _fail(*a, **k):
        return {"ok": False, "reason": "돋보기 없음"}

    monkeypatch.setattr(query.steps, "set_gwaprvlst", _fail)
    out = await make_set_query_node()({"events": _q(), "page": _FakePage()})
    assert "전자결재상태" in out["error"] and "돋보기 없음" in out["error"]
    assert_keys_declared(VoucherReceivableState, out)


async def test_set_query_short_circuits():
    out = await make_set_query_node()({"events": _q(), "error": "x", "page": _FakePage()})
    assert out == {}


# ── run_query ─────────────────────────────────────────────────────────────────
async def test_run_query_stores_rowcount(monkeypatch):
    async def _ok(page):
        return {"ok": True, "rowcount": 31}

    monkeypatch.setattr(query.steps, "run_query", _ok)
    out = await make_run_query_node()({"events": _q(), "page": _FakePage()})
    assert out == {"master_rowcount": 31}
    assert_keys_declared(VoucherReceivableState, out)


async def test_run_query_zero_is_ok(monkeypatch):
    async def _zero(page):
        return {"ok": True, "rowcount": 0}

    monkeypatch.setattr(query.steps, "run_query", _zero)
    out = await make_run_query_node()({"events": _q(), "page": _FakePage()})
    assert out == {"master_rowcount": 0}


async def test_run_query_grid_unreadable_errors(monkeypatch):
    async def _fail(page):
        return {"ok": False, "reason": "rowcount 못 읽음", "rowcount": -1}

    monkeypatch.setattr(query.steps, "run_query", _fail)
    out = await make_run_query_node()({"events": _q(), "page": _FakePage()})
    assert "error" in out and "못 읽" in out["error"]
    assert_keys_declared(VoucherReceivableState, out)


# ── loop_approvals ────────────────────────────────────────────────────────────
class _RecordingChild:
    """결제창(자식 Page) 스텁 — 호출 메서드를 전부 기록해 '상신/보관 미클릭'을 행위로 검증한다.

    상단 버튼 텍스트에 상신·보관을 포함해 반환하지만, 노드가 그걸 클릭하지 않아야 한다.
    click/mouse 접근은 접근 자체를 실패로 만들어 원천 차단한다.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.closed = False

    async def wait_for_load_state(self, *a, **k):
        self.calls.append("wait_for_load_state")

    async def wait_for_timeout(self, ms):
        self.calls.append("wait_for_timeout")

    async def evaluate(self, js_src, arg=None):
        self.calls.append("evaluate")
        return [
            {"text": "상신", "x": 922, "y": 30, "visible": True},
            {"text": "보관", "x": 860, "y": 30, "visible": True},
            {"text": "미리보기", "x": 780, "y": 30, "visible": True},
        ]

    async def close(self):
        self.calls.append("close")
        self.closed = True

    @property
    def mouse(self):  # noqa: D401 — 접근 시 즉시 실패(상신/보관 클릭 시도 감지).
        raise AssertionError("결제창 mouse 접근 금지 — 상신/보관 클릭 위험")

    async def click(self, *a, **k):
        raise AssertionError("결제창 click 금지 — 상신/보관")


def _patch_loop(monkeypatch, child, *, check_ok=True, open_child=True):
    async def _key(page, idx):
        return f"FI202607010000{idx:04d}"

    async def _uncheck(page):
        return True

    async def _check(page, idx):
        return check_ok

    async def _open(page):
        return child if open_child else None

    monkeypatch.setattr(approvals.steps, "read_row_key", _key)
    monkeypatch.setattr(approvals.steps, "uncheck_all_rows", _uncheck)
    monkeypatch.setattr(approvals.steps, "check_row", _check)
    monkeypatch.setattr(approvals.steps, "open_approval", _open)
    # poll_child_ready / close_child 는 실제 구현을 그대로 쓴다(자식 Page 상호작용을 실검증).


async def test_loop_zero_rows_completes():
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": object(), "master_rowcount": 0, "max_rows": 1})
    assert out["processed"] == 0 and out["processed_docu_nos"] == []
    assert "대상 전표가 없" in out["result"]
    assert_keys_declared(VoucherReceivableState, out)


async def test_loop_single_row_virtual_submit_never_clicks(monkeypatch):
    child = _RecordingChild()
    _patch_loop(monkeypatch, child)
    q = _q()
    node = make_loop_approvals_node()
    out = await node({"events": q, "page": object(), "master_rowcount": 5, "max_rows": 1})

    # 단일행 게이트: rowcount 5 여도 max_rows=1 이면 1건만.
    assert out["processed"] == 1
    assert out["processed_docu_nos"] == ["FI2026070100000000"]
    assert_keys_declared(VoucherReceivableState, out)

    # ⚠ 절대 안전(행위 검증): 결제창에 한 일은 읽기+닫기뿐 — click/mouse 미접근.
    assert child.closed is True
    assert set(child.calls) <= {"wait_for_load_state", "wait_for_timeout", "evaluate", "close"}
    assert "close" in child.calls

    # 가상 상신 로그가 DOCU_NO 를 남긴다.
    logs = _logs(_drain(q))
    # 가상 상신 로그에 진행 표기([i/N])와 DOCU_NO 가 함께 담긴다.
    assert any("가상 상신" in m and "FI2026070100000000" in m for m in logs)
    assert any(m.startswith("[1/1]") for m in logs)  # 진행 상황 노출


async def test_loop_batch_processes_min_of_max_and_rowcount(monkeypatch):
    child = _RecordingChild()
    _patch_loop(monkeypatch, child)
    node = make_loop_approvals_node()
    # max_rows=3, rowcount=2 → 2건(min).
    out = await node({"events": _q(), "page": object(), "master_rowcount": 2, "max_rows": 3})
    assert out["processed"] == 2
    assert out["processed_docu_nos"] == ["FI2026070100000000", "FI2026070100000001"]
    assert child.closed is True


async def test_loop_default_none_processes_all_rows(monkeypatch):
    # 전체 진행(사용자 결정 2026-07-21): max_rows 미지정/None → 조회된 전 건 순회.
    child = _RecordingChild()
    _patch_loop(monkeypatch, child)
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": object(), "master_rowcount": 5})  # max_rows 없음 = 전체
    assert out["processed"] == 5
    assert out["processed_docu_nos"] == [f"FI202607010000{i:04d}" for i in range(5)]


async def test_loop_emits_progress_i_of_n(monkeypatch):
    # 진행 상황 노출(사용자 요청 2026-07-21): 총 건수 + 몇 건 중 몇 번째 + 누적 실행 건수.
    child = _RecordingChild()
    _patch_loop(monkeypatch, child)
    node = make_loop_approvals_node()
    q = _q()
    out = await node({"events": q, "page": object(), "master_rowcount": 3})  # 전체(None)
    assert out["processed"] == 3
    frames = _drain(q)
    logs = _logs(frames)
    assert any("대상 3건" in m for m in logs)  # 시작 배너에 총 건수
    for i in (1, 2, 3):  # 각 건 [i/3] 진행 표기
        assert any(m.startswith(f"[{i}/3]") for m in logs)
    assert any("누적 3/3" in m for m in logs)  # 최종 누적 실행 건수
    assert any("대상 3건 중 3건 가상 상신" in m for m in logs)  # 완료 배너
    # 워크플로우 노드용 step progress 프레임(done/total) 방출 — 0/3 시작 ~ 3/3 완료.
    prog = [f["progress"] for f in frames if f.get("step") == "loop_approvals" and "progress" in f]
    assert {p["total"] for p in prog} == {3}
    dones = [p["done"] for p in prog]
    assert 0 in dones and 3 in dones


async def test_loop_batch_checks_exactly_one_row_at_each_approval(monkeypatch):
    """리뷰 HIGH-2 회귀: 배치(2행) 순회에서 결재창을 여는 순간 정확히 한 행만 체크돼 있어야 한다.

    직전 대상 행의 체크가 남으면 결재가 여러 문서를 잡을 위험 — 대상 행 checkRow 전에
    uncheck_all_rows 로 전체 해제해 매 결재 오픈 시 체크 수가 1 이 되도록 한다.
    """
    child = _RecordingChild()
    checked: set[int] = set()
    checked_at_approval: list[int] = []

    async def _key(page, idx):
        return f"FI{idx}"

    async def _uncheck(page):
        checked.clear()
        return True

    async def _check(page, idx):
        checked.add(idx)
        return True

    async def _open(page):
        checked_at_approval.append(len(checked))  # 결재창 오픈 순간의 체크 행 수 스냅샷.
        return child

    monkeypatch.setattr(approvals.steps, "read_row_key", _key)
    monkeypatch.setattr(approvals.steps, "uncheck_all_rows", _uncheck)
    monkeypatch.setattr(approvals.steps, "check_row", _check)
    monkeypatch.setattr(approvals.steps, "open_approval", _open)

    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": object(), "master_rowcount": 2, "max_rows": 2})
    assert out["processed"] == 2
    # 두 번의 결재 오픈 모두에서 정확히 1행만 체크(직전 행 체크가 해제됨).
    assert checked_at_approval == [1, 1]


async def test_loop_check_row_failure_errors(monkeypatch):
    child = _RecordingChild()
    _patch_loop(monkeypatch, child, check_ok=False)
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": object(), "master_rowcount": 3, "max_rows": 1})
    assert "checkRow" in out["error"]
    assert_keys_declared(VoucherReceivableState, out)
    # 행 선택 실패면 결제창을 열지 않았어야 한다.
    assert child.closed is False


async def test_loop_no_child_page_errors(monkeypatch):
    child = _RecordingChild()
    _patch_loop(monkeypatch, child, open_child=False)
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": object(), "master_rowcount": 1, "max_rows": 1})
    assert "결재창" in out["error"]
    assert_keys_declared(VoucherReceivableState, out)


async def test_loop_short_circuits_on_prior_error():
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "error": "이전 실패", "page": object()})
    assert out == {}


# ── 정적 소스 스캔 가드: 결제창 상신/보관 클릭 경로가 소스에 아예 없어야 한다 ──────────
async def test_source_never_clicks_child_submit_or_archive():
    src = inspect.getsource(vsteps) + "\n" + inspect.getsource(approvals)
    # 자식 Page(child) 를 클릭하는 코드가 없어야 한다.
    assert "mouse_click(child" not in src
    assert "child.click" not in src
    assert "child.mouse" not in src
    # 상단 버튼 탐지 JS 는 읽기 전용 — 클릭 호출이 없어야 한다.
    assert ".click(" not in vjs.CHILD_TOP_BUTTONS_JS
    # loop 노드는 자식 Page 를 직접 클릭하지 않는다(모든 클릭은 부모 page 대상 steps 경유).
    assert "mouse_click" not in inspect.getsource(approvals)


# ── open_approval: 결재 클릭 '전에' expect_page 를 등록해야 한다(별도 Page 감지 계약) ──
class _FakePageInfo:
    def __init__(self, child):
        self._child = child

    @property
    def value(self):
        async def _v():
            return self._child

        return _v()


class _FakeExpectPage:
    def __init__(self, child, clicked):
        self._child = child
        self._clicked = clicked

    async def __aenter__(self):
        # 리스너는 결재 클릭 전에 등록돼야 한다(SSO 팝업 유실 방지).
        assert self._clicked[0] is False, "expect_page 진입은 결재 클릭 전이어야 한다"
        return _FakePageInfo(self._child)

    async def __aexit__(self, *a):
        return False


class _FakeApprovalPage:
    def __init__(self, child):
        self._child = child
        self.clicked = [False]
        page = self

        class _Ctx:
            def expect_page(self):
                return _FakeExpectPage(page._child, page.clicked)

        class _Mouse:
            async def click(self, x, y):
                page.clicked[0] = True

        self.context = _Ctx()
        self.mouse = _Mouse()

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.LOADING_OVERLAY_VISIBLE_JS:
            return False  # 오버레이 없음 — 즉시 클릭 진행.
        return {"x": 1317, "y": 72}  # APPROVAL_BTN_RECT_JS


async def test_open_approval_registers_listener_before_click():
    child = _RecordingChild()
    page = _FakeApprovalPage(child)
    got = await vsteps.open_approval(page)
    assert got is child
    assert page.clicked[0] is True  # 클릭은 실제로 일어났다(리스너 등록 후).


# ── open_approval 반복 호출 견고화(2026-07-21 배치 라이브 실측: 2건째 미출현) ──────────
class _RetryExpectPage:
    """expect_page() 컨텍스트 — should_fail=True 면 __aexit__ 에서 예외를 던져 '새 Page
    미출현(타임아웃)'을 흉내낸다. Playwright 실제 계약과 동일하게 대기/확정은 __aexit__ 이후."""

    def __init__(self, should_fail: bool, child) -> None:
        self._should_fail = should_fail
        self._child = child

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._should_fail:
            raise TimeoutError("no new page (fake)")
        return False

    @property
    def value(self):
        async def _v():
            return self._child

        return _v()


class _RetryApprovalPage:
    """open_approval 재시도 검증용 — 처음 fail_times 회는 expect_page 가 실패하고, 이후엔
    성공한다. rect 평가·정착 대기 호출 횟수를 기록해 '매 시도 새로 평가'를 검증한다."""

    def __init__(self, fail_times: int, child) -> None:
        self._fail_times = fail_times
        self._child = child
        self._attempts = 0
        self.rect_evaluations = 0
        self.waits: list[int] = []
        page = self

        class _Ctx:
            def expect_page(ctx_self):
                page._attempts += 1
                return _RetryExpectPage(page._attempts <= page._fail_times, page._child)

        class _Mouse:
            async def click(self, x, y):
                return None

        self.context = _Ctx()
        self.mouse = _Mouse()

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.LOADING_OVERLAY_VISIBLE_JS:
            return False  # 오버레이 없음 — rect 카운트에 포함하지 않는다.
        self.rect_evaluations += 1
        return {"x": 1317, "y": 72}

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


async def test_open_approval_retries_after_first_expect_page_timeout():
    """2026-07-21 실측: 1건째 성공 후 2건째에서 새 Page 미출현 관찰 — bounded 재시도로 방어.
    실패 후 재시도 시 버튼 rect 를 캐시하지 않고 다시 읽는다."""
    child = _RecordingChild()
    page = _RetryApprovalPage(fail_times=1, child=child)
    got = await vsteps.open_approval(page)
    assert got is child
    assert page.rect_evaluations == 2  # 실패 후 rect 를 다시(새로) 읽었다(캐시 아님).
    assert page.waits == [500]  # 실패~재시도 사이 정착 대기 1회.


async def test_open_approval_gives_up_after_max_attempts():
    """모든 시도가 실패하면 무한 재시도 없이 상한(attempts)에서 None 을 돌려준다."""
    child = _RecordingChild()
    page = _RetryApprovalPage(fail_times=99, child=child)  # 항상 실패.
    got = await vsteps.open_approval(page, attempts=2)
    assert got is None
    assert page.rect_evaluations == 2


# ── wait_loading_overlay_gone: 근본원인 확정 회귀(2026-07-21 읽기전용 진단) ─────────────
# check_row(setCurrent)가 트리거하는 `.dews-loading-bg` 오버레이가 결재 버튼 클릭을 가로채
# 2건째 결제창이 안 뜨던 문제의 확정 원인 — 클릭 전 오버레이가 사라질 때까지 폴링해야 한다.
class _OverlayFakePage:
    def __init__(self, visible_for_polls: int) -> None:
        self.polls = 0
        self.waits: list[int] = []
        self._visible_for = visible_for_polls

    async def evaluate(self, js_src, arg=None):
        assert js_src == vjs.LOADING_OVERLAY_VISIBLE_JS
        self.polls += 1
        return self.polls <= self._visible_for

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


async def test_wait_loading_overlay_gone_polls_until_hidden():
    page = _OverlayFakePage(visible_for_polls=3)
    ok = await vsteps.wait_loading_overlay_gone(page, interval_ms=10)
    assert ok is True
    assert page.polls == 4  # 3회 visible + 1회 확인(hidden).


async def test_wait_loading_overlay_gone_returns_false_after_cap():
    page = _OverlayFakePage(visible_for_polls=9999)  # 계속 안 사라짐.
    ok = await vsteps.wait_loading_overlay_gone(page, cap_ms=30, interval_ms=10)
    assert ok is False


async def test_wait_loading_overlay_gone_absorbs_incompatible_stub():
    """스텁이 evaluate/wait_for_timeout 을 못 갖춰도 예외 없이 True(best-effort)."""
    ok = await vsteps.wait_loading_overlay_gone(object())
    assert ok is True


async def test_open_approval_waits_for_overlay_before_each_click():
    """open_approval 이 매 시도마다 클릭 전 오버레이 소거를 기다린다(회귀 방지)."""
    child = _RecordingChild()

    class _OverlayThenApprovalPage(_RetryApprovalPage):
        def __init__(self, child) -> None:
            super().__init__(fail_times=0, child=child)
            self.overlay_polls = 0

        async def evaluate(self, js_src, arg=None):
            if js_src == vjs.LOADING_OVERLAY_VISIBLE_JS:
                self.overlay_polls += 1
                return self.overlay_polls <= 2  # 2회는 보이다가 사라짐.
            return await super().evaluate(js_src, arg)

    page = _OverlayThenApprovalPage(child)
    got = await vsteps.open_approval(page)
    assert got is child
    assert page.overlay_polls >= 3  # 사라짐 확인까지 폴링했다.


# ── settle_parent_after_child_close: 자식 닫힘 확인 → 포그라운드 복귀 → 버튼 재가시 폴링 ──
class _SettleFakeChild:
    def __init__(self, closed_after_checks: int) -> None:
        self._checks = 0
        self._closed_after = closed_after_checks

    def is_closed(self) -> bool:
        self._checks += 1
        return self._checks >= self._closed_after


class _SettleFakePage:
    def __init__(self, approval_visible_after_polls: int) -> None:
        self.waits: list[int] = []
        self.brought_to_front = False
        self._polls = 0
        self._visible_after = approval_visible_after_polls

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)

    async def bring_to_front(self):
        self.brought_to_front = True

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.LOADING_OVERLAY_VISIBLE_JS:
            return False  # 로딩 없음 — 근본원인 수정(close 직후 로딩 대기)을 즉시 통과.
        assert js_src == vjs.APPROVAL_BTN_RECT_JS
        self._polls += 1
        if self._polls >= self._visible_after:
            return {"x": 1, "y": 1}
        return None


async def test_settle_parent_after_child_close_waits_close_then_front_then_button():
    child = _SettleFakeChild(closed_after_checks=3)
    page = _SettleFakePage(approval_visible_after_polls=2)
    await vsteps.settle_parent_after_child_close(page, child)
    assert page.brought_to_front is True
    assert page._polls >= 2  # 결재 버튼이 다시 보일 때까지 폴링했다.


async def test_settle_parent_after_child_close_absorbs_incompatible_stub():
    """페이지/자식 스텁이 is_closed/bring_to_front/evaluate 를 갖추지 못해도(단위테스트 등)
    예외 없이 조용히 반환한다(best-effort — open_approval 의 재시도가 최종 방어선)."""
    await vsteps.settle_parent_after_child_close(object(), object())  # 예외 없이 반환해야 함.


class _SettleLoadingFakePage:
    """settle_parent_after_child_close 가 close 직후 본창 로딩을 실제로 기다리는지 검증한다
    (도메인전문가 확정 근본원인 회귀 테스트) — 호출 순서와 오버레이 폴링 횟수를 기록."""

    def __init__(self, overlay_visible_for_polls: int) -> None:
        self.calls: list[str] = []
        self.overlay_polls = 0
        self._overlay_visible_for = overlay_visible_for_polls

    async def wait_for_timeout(self, ms):
        self.calls.append(f"wait:{ms}")

    async def bring_to_front(self):
        self.calls.append("bring_to_front")

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.LOADING_OVERLAY_VISIBLE_JS:
            self.overlay_polls += 1
            self.calls.append("overlay_check")
            return self.overlay_polls <= self._overlay_visible_for
        self.calls.append("rect_check")
        return {"x": 1, "y": 1}  # 결재 버튼 즉시 유효.


async def test_settle_parent_after_child_close_waits_for_loading_before_front_and_button():
    """근본원인 회귀(도메인전문가 확정, 2026-07-21): "결제 팝업을 닫으면 본창에서 별도 처리가
    진행되고 로딩이 걸린다. 그 로딩이 끝나기 전에 다음 행을 체크하고 결제를 다시 호출해서
    안 되는 것" — close 직후 로딩 인디케이터가 사라질 때까지 **실제로 폴링**하고, 그 폴링이
    bring_to_front/버튼폴링보다 **먼저** 온다(순서 검증)."""
    child = _SettleFakeChild(closed_after_checks=1)  # 즉시 닫힘 확인.
    page = _SettleLoadingFakePage(overlay_visible_for_polls=3)
    await vsteps.settle_parent_after_child_close(page, child)
    assert page.overlay_polls >= 4  # 3회 visible + 1회 확인(hidden) 이상 폴링했다.
    first_bring = page.calls.index("bring_to_front")
    last_overlay = max(i for i, c in enumerate(page.calls) if c == "overlay_check")
    assert last_overlay < first_bring  # 로딩 대기가 포그라운드 복귀보다 먼저 끝난다.


# ── ensure_field_visible: 결과검증형 확장(도메인전문가 실측, 2026-07-21) ─────────────
class _VisFakeMouse:
    def __init__(self, page: "_VisFakePage") -> None:
        self._page = page

    async def click(self, x, y):
        self._page.clicks.append((x, y))


class _VisFakePage:
    """ensure_field_visible 테스트용 — FIELD_LABEL_VISIBLE_JS/EXPAND_TOGGLE_RECTS_JS 를
    시나리오별로 스텁하고 클릭 좌표를 기록한다(어느 토글까지 시도했는지 검증)."""

    def __init__(self, *, visible_after_clicks: int, toggle_rects: list[dict]) -> None:
        self.visible_after_clicks = visible_after_clicks
        self.toggle_rects = toggle_rects
        self.clicks: list[tuple[int, int]] = []
        self.mouse = _VisFakeMouse(self)

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.FIELD_LABEL_VISIBLE_JS:
            return len(self.clicks) >= self.visible_after_clicks
        if js_src == vjs.EXPAND_TOGGLE_RECTS_JS:
            return self.toggle_rects
        raise AssertionError(f"unexpected evaluate call: {js_src[:60]!r}")

    async def wait_for_timeout(self, ms):
        return None


async def test_ensure_field_visible_already_visible_clicks_nothing():
    """이미 보이면 어떤 토글도 누르지 않는다(역방향 접힘 방지 — 이미 펼쳐진 토글을 다시
    누르면 접힐 수 있다)."""
    page = _VisFakePage(visible_after_clicks=0, toggle_rects=[{"x": 1, "y": 1}])
    ok = await vsteps.ensure_field_visible(page, "전표유형")
    assert ok is True
    assert page.clicks == []


async def test_ensure_field_visible_tries_toggles_left_to_right_until_visible():
    """숨김 상태면 좌→우 순으로 토글을 하나씩 결과검증형으로 눌러본다(여러 토글 시나리오,
    도메인전문가 실측: 확장 토글이 여러 개일 수 있고 어느 것이 목표 필드를 드러내는지 미리
    알 수 없다). 목표가 보이면 그 이상은 누르지 않는다."""
    rects = [{"x": 100, "y": 10}, {"x": 200, "y": 10}, {"x": 300, "y": 10}]
    page = _VisFakePage(visible_after_clicks=2, toggle_rects=rects)
    ok = await vsteps.ensure_field_visible(page, "전표유형")
    assert ok is True
    assert page.clicks == [(100, 10), (200, 10)]  # 세 번째 토글은 누르지 않았다.


async def test_ensure_field_visible_gives_up_after_max_toggles():
    """어떤 토글로도 목표 필드가 보이지 않으면 False(무한 클릭 금지, max_toggles 상한)."""
    rects = [{"x": 100, "y": 10}, {"x": 200, "y": 10}]
    page = _VisFakePage(visible_after_clicks=99, toggle_rects=rects)
    ok = await vsteps.ensure_field_visible(page, "전표유형", max_toggles=2)
    assert ok is False
    assert page.clicks == [(100, 10), (200, 10)]


# ── set_docu_types: SYSDEF_NM 필드 회귀(2026-07-21 실측 — DOCU_NM 아님) ────────────
class _DocuTypesFakePage:
    """set_docu_types 가 팝업 체크 JS 를 어떤 fieldName 으로 호출하는지 기록한다."""

    def __init__(self) -> None:
        self.mouse = _VisFakeMouse(self)  # type: ignore[arg-type]
        self.clicks: list[tuple[int, int]] = []
        self.check_rows_arg: list | None = None

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.FIELD_LABEL_VISIBLE_JS:
            return True  # 이미 보임 — 토글 불필요.
        if js_src == vjs.FIELD_SEARCH_BTN_RECT_JS:
            return {"x": 10, "y": 10}
        if js_src == vjs.POPUP_CHECK_ROWS_JS:
            self.check_rows_arg = arg
            targets, _field = arg
            idxs = [{"t": t, "idx": i, "code": str(20 + i)} for i, t in enumerate(targets)]
            return {"ok": True, "idxs": idxs, "n": 62}
        if js_src == vjs.POPUP_APPLY_BTN_JS:
            return {"x": 20, "y": 20}
        raise AssertionError(f"unexpected evaluate call: {js_src[:60]!r}")

    async def wait_for_timeout(self, ms):
        return None


async def test_set_docu_types_queries_sysdef_nm_field():
    """회귀(2026-07-21 읽기전용 진단 실측): 전표유형 팝업의 실제 필드는 전자결재상태 팝업과
    동일한 범용 코드테이블 스키마 SYSDEF_NM 이다 — 'DOCU_NM' 아님(이전 프로브 기록 오류)."""
    page = _DocuTypesFakePage()
    res = await vsteps.set_docu_types(page)
    assert res["ok"] is True
    assert page.check_rows_arg is not None
    assert page.check_rows_arg[1] == "SYSDEF_NM"


# ── D7(배치 순회 정합성) — 행/팝업 어긋남 안전 크리티컬 검증(2026-07-21 배치 라이브 스모크) ──
class _D7Page:
    """checked_row_indexes 용 — CHECKED_ROW_INDEXES_JS 호출에 지정된 결과를 돌려준다."""

    def __init__(self, checked_rows: list[int]) -> None:
        self._checked_rows = checked_rows

    async def evaluate(self, js_src, arg=None):
        if js_src == vjs.CHECKED_ROW_INDEXES_JS:
            return {"ok": True, "rows": self._checked_rows}
        raise AssertionError(f"unexpected page.evaluate: {js_src[:60]!r}")


class _D7Child(_RecordingChild):
    """read_child_docu_no 용 — CHILD_DOCU_NO_JS 호출에 지정된 매치를 돌려준다(그 외엔 기존
    캔드 상단버튼 목록을 유지해 poll_child_ready 를 그대로 통과시킨다)."""

    def __init__(self, docu_matches: list[str]) -> None:
        super().__init__()
        self._docu_matches = docu_matches

    async def evaluate(self, js_src, arg=None):
        self.calls.append("evaluate")
        if js_src == vjs.CHILD_DOCU_NO_JS:
            return self._docu_matches
        return [
            {"text": "상신", "x": 922, "y": 30, "visible": True},
            {"text": "보관", "x": 860, "y": 30, "visible": True},
            {"text": "미리보기", "x": 780, "y": 30, "visible": True},
        ]


async def test_loop_confirmed_docu_no_mismatch_aborts(monkeypatch):
    """D7 안전 크리티컬: 결제창 전표번호가 예상 DOCU_NO 와 확정적으로(매치 정확히 1개) 다르면
    배치를 즉시 중단한다(코디네이터 지시 — 어긋남 감지 시 계속 진행 금지). 결제창은 닫는다."""
    child = _D7Child(["FI9999999999999999"])  # 예상(idx0=FI2026070100000000)과 다른 값.
    _patch_loop(monkeypatch, child)
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": object(), "master_rowcount": 3, "max_rows": 3})
    assert "불일치" in out["error"]
    assert child.closed is True  # 중단해도 결제창은 반드시 닫는다.
    assert out["processed"] == 0  # 불일치 행은 처리건수에 포함하지 않는다.
    assert out["processed_docu_nos"] == []


async def test_loop_ambiguous_docu_no_match_still_processes(monkeypatch):
    """후보가 0개/2개+ 면 확정 불일치가 아니므로(패턴 모호) 경고만 남기고 정상 처리한다
    (셀렉터 불확실성으로 인한 오탐이 배치를 중단시키지 않도록)."""
    child = _D7Child(["FI2026070100000000", "FI2026070100000099"])  # 2개 매치 = 모호.
    _patch_loop(monkeypatch, child)
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": object(), "master_rowcount": 1, "max_rows": 1})
    assert out["processed"] == 1
    assert out["processed_docu_nos"] == ["FI2026070100000000"]
    assert child.closed is True


async def test_loop_checked_rowcount_violation_aborts_before_opening_approval(monkeypatch):
    """D7: 결제 열기 직전 체크된 행이 1이 아니면(직전 행 체크 잔존 등) 결제창을 아예 열지
    않고 즉시 중단한다."""

    async def _key(page, idx):
        return "FI2026070100000000"

    async def _uncheck(page):
        return True

    async def _check(page, idx):
        return True

    opened: list[bool] = []

    async def _open(page):
        opened.append(True)
        return _RecordingChild()

    monkeypatch.setattr(approvals.steps, "read_row_key", _key)
    monkeypatch.setattr(approvals.steps, "uncheck_all_rows", _uncheck)
    monkeypatch.setattr(approvals.steps, "check_row", _check)
    monkeypatch.setattr(approvals.steps, "open_approval", _open)

    page = _D7Page(checked_rows=[0, 1])  # 2행 체크됨 — 위반.
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": page, "master_rowcount": 1, "max_rows": 1})
    assert "체크된 행 수" in out["error"]
    assert opened == []  # 결제창을 아예 열지 않았다.


async def test_loop_checked_rowcount_ok_when_exactly_one(monkeypatch):
    """체크된 행이 정확히 1개면 정상 진행(회귀 방지 — 정상 케이스가 오탐으로 막히지 않게)."""
    child = _RecordingChild()
    _patch_loop(monkeypatch, child)

    async def _checked_ok(page):
        return {"ok": True, "rows": [0]}

    monkeypatch.setattr(approvals.steps, "checked_row_indexes", _checked_ok)
    node = make_loop_approvals_node()
    out = await node({"events": _q(), "page": object(), "master_rowcount": 1, "max_rows": 1})
    assert out["processed"] == 1
    assert child.closed is True
