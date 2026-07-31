"""잔존 고정 sleep → 조건 폴링 전환(2026-07-31) — 에이전트 측 전환 지점 대표 케이스.

전환 계약(공통): 즉시 준비 = 빠른 통과(고정 대기 소진 없음) / 늦은 준비 = 신호 도착 시점에
통과 / 미준비 = 상한(실시간 monotonic × latency 배율) 소진 후 기존 실패·폴백 수순 그대로.

대상:
  - voucher_receivable._open_picker — 고정 1200ms 선대기 제거(팝업 개수 증가+그리드 ready
    조건 폴링으로 일원화).
  - trip_domestic._poll_rowcount_over — dump_partners 서버 페이징 도착(고정 3s/2s 대체).
  - card_collect.mgmt_items — 차량 팝업 오픈(고정 1.2s 대체)·적용 반영 readback(고정 1.2s 대체).
"""

from __future__ import annotations

import pytest

from app.agents.card_collect import mgmt_items
from app.agents.trip_domestic import steps as tsteps
from app.agents.voucher_receivable import js as vjs
from app.agents.voucher_receivable import steps as vsteps
from nbkit.omnisol import js_lib, latency

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_latency():
    latency.reset()
    yield
    latency.reset()


class _Mouse:
    def __init__(self, sink: list) -> None:
        self._sink = sink

    async def click(self, x, y):
        self._sink.append((x, y))


# ── voucher _open_picker: 고정 1200ms 선대기 제거 ─────────────────────────────────
class _FastPickerPage:
    """돋보기 클릭 즉시 팝업이 뜨고 그리드가 붙는 페이지 — wait 호출 수를 센다."""

    def __init__(self) -> None:
        self.clicks: list = []
        self.mouse = _Mouse(self.clicks)
        self.waits: list[int] = []

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.NOTICE_POPUP_BOXES_JS:
            return None
        if js_src == vjs.FIELD_SEARCH_BTN_RECT_JS:
            return {"x": 7, "y": 8}
        if js_src == vjs.POPUP_COUNT_JS:
            return 1 if (7, 8) in self.clicks else 0
        if js_src == vjs.POPUP_GRID_READY_JS:
            return True
        raise AssertionError(f"unexpected evaluate: {js_src[:60]!r}")

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


async def test_open_picker_no_fixed_presleep_when_ready_immediately():
    """즉시 준비 = 빠른 통과 — 종전에는 조건과 무관하게 고정 1200ms 를 먼저 태웠다.
    이제 첫 조건 확인(개수 증가+그리드 ready)에서 통과하면 wait 호출이 0회다."""
    page = _FastPickerPage()
    ok = await vsteps._open_picker(page, "전자결재상태")
    assert ok is True
    assert page.waits == []  # 고정 선대기 소멸 — 조건 충족 즉시 진행.


# ── trip_domestic._poll_rowcount_over: 페이징 도착 즉시 진행 ─────────────────────
class _RowcountPage:
    """PICKER_ROWCOUNT_JS 를 시퀀스로 응답(소진되면 마지막 값 유지) + 가짜 시계."""

    def __init__(self, seq: list[int]) -> None:
        self._seq = list(seq)
        self.clock_ms = 0.0

    async def evaluate(self, js_src, arg=None):
        assert js_src is js_lib.PICKER_ROWCOUNT_JS
        return self._seq.pop(0) if len(self._seq) > 1 else self._seq[0]

    async def wait_for_timeout(self, ms):
        self.clock_ms += ms

    def install_clock(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.agents.trip_domestic.steps.time.monotonic", lambda: self.clock_ms / 1_000
        )


async def test_poll_rowcount_over_returns_as_soon_as_rows_arrive(monkeypatch):
    """늦은 준비 = 도착 시점에 통과 — 3번째 폴에서 행이 늘면(3→7) 즉시 반환한다(종전 고정
    3s 는 도착 후에도 남은 시간을 통째로 태웠다)."""
    page = _RowcountPage([3, 3, 7])
    page.install_clock(monkeypatch)
    cur = await tsteps._poll_rowcount_over(page, 3, cap_ms=3_000)
    assert cur == 7
    assert page.clock_ms == 600  # 2회 대기(300ms×2) 후 도착 — 상한(3s)을 태우지 않았다.


async def test_poll_rowcount_over_caps_when_no_growth(monkeypatch):
    """미준비 = 상한 소진 후 마지막 값 반환 — 호출부 stable 카운트(종료 판정)가 기존 수순대로
    이어진다(고정 3s 관찰과 동일한 의미)."""
    page = _RowcountPage([3])
    page.install_clock(monkeypatch)
    cur = await tsteps._poll_rowcount_over(page, 3, cap_ms=1_000)
    assert cur == 3
    assert page.clock_ms >= 1_000  # 상한(×factor 1.0)까지 관찰했다.


# ── mgmt_items: 차량 팝업 오픈 폴링 + 적용 반영 readback 폴링 ─────────────────────
class _VehiclePage:
    """관리항목(업무용차량) 스텝 FakePage — 덤프/READ 값을 호출 횟수로 제어한다."""

    def __init__(self, *, dump_ok_after: int = 0, reflect_code_after: int = 0, code: str = "V1") -> None:
        self._dump_ok_after = dump_ok_after
        self._reflect_after = reflect_code_after
        self._code = code
        self.dump_calls = 0
        self.read_calls = 0
        self.clicks: list = []
        self.mouse = _Mouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        if js_src is mgmt_items._ROW_SCROLL_JS:
            return True
        if js_src is mgmt_items._ROW_BUTTON_JS:
            return {"x": 5, "y": 6}
        if js_src is mgmt_items._VEHICLE_POPUP_DUMP_JS:
            self.dump_calls += 1
            if self.dump_calls > self._dump_ok_after:
                return {"ok": True, "n": 1, "rows": [{"code": self._code, "name": "차량"}]}
            return {"ok": False, "reason": "no-popup"}
        if js_src is mgmt_items._ROW_VALUES_JS:
            self.read_calls += 1
            if self.read_calls > self._reflect_after:
                return {"found": True, "code": self._code, "name": "차량"}
            return {"found": True, "code": "", "name": ""}
        raise AssertionError(f"unexpected evaluate: {str(js_src)[:60]!r}")

    async def wait_for_timeout(self, ms):
        return None


async def test_open_vehicle_popup_waits_until_rows_arrive():
    """차량 팝업 덤프가 늦게 준비돼도(2회차부터 ok) 폴링으로 잡는다 — 종전 고정 1.2s 후
    1회 덤프는 이보다 늦게 뜨는 팝업을 실패로 오판했다."""
    page = _VehiclePage(dump_ok_after=1)
    res = await mgmt_items._open_vehicle_popup(page)
    assert res["ok"] is True
    assert res["rows"][0]["code"] == "V1"
    assert page.dump_calls >= 2  # 1회차 미준비 → 폴링으로 재확인.


async def test_poll_vehicle_reflected_immediate_and_late():
    """반영 readback: 즉시 반영 = 1회 읽기로 통과, 늦은 반영 = 반영 시점에 통과."""
    fast = _VehiclePage(reflect_code_after=0)
    rb = await mgmt_items._poll_vehicle_reflected(fast, "V1")
    assert rb["code"] == "V1" and fast.read_calls == 1

    late = _VehiclePage(reflect_code_after=2)
    rb = await mgmt_items._poll_vehicle_reflected(late, "V1")
    assert rb["code"] == "V1" and late.read_calls == 3


async def test_poll_vehicle_reflected_caps_and_reports_last_readback():
    """미반영 = 상한 소진 후 마지막 readback 반환 — 호출부의 코드 불일치 실패 보고(성공 단정
    금지)가 기존 수순대로 동작한다."""
    page = _VehiclePage(reflect_code_after=10_000)  # 절대 반영 안 됨.
    rb = await mgmt_items._poll_vehicle_reflected(page, "V1", cap_ms=100)
    assert (rb.get("code") or "") != "V1"  # 반영 실패를 사실대로 돌려준다.
