"""사용자유형 전환 조건 폴링(2026-07-31 전환) — 고정 sleep 제거 계약을 FakePage 로 고정.

배경: 느린 네트워크에서 고정 sleep(1s+1s+2.5s+1.5s + networkidle 12s ≈ 18s)은 "확인 없이
너무 일찍 진행"하는 레이스(삭제 모달 사고 유형)와 "정상 경로에서도 매번 소진"을 함께 만든다.
전환 후 계약:
  - 드롭다운 옵션 렌더·선택 반영·변경적용 reload 를 각각 **상태 신호**(UT_OPTION_BOX_JS
    좌표 안정 / UT_DISPLAY_JS target 반영 / 마커 소멸→아바타 재출현)로 폴링한다.
  - 즉시 준비 = 빠른 통과, 늦은 준비 = 대기 후 통과, 미준비 = 기존 attempts=2 재시도·실패.
  - 상한은 실시간(monotonic) × latency 배율 — 가짜 시계(install_clock)로 낭비 없이 소진한다.
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import auth, js_lib, latency, selectors
from nbkit.omnisol.errors import UserTypeError

pytestmark = pytest.mark.asyncio

_SELECTOR_PRESENT_JS = "(s) => !!document.querySelector(s)"


class _Mouse:
    def __init__(self, page: "_UtSwitchPage") -> None:
        self._p = page

    async def click(self, x, y):
        self._p.clicks.append((x, y))
        if (x, y) == (2, 2):
            self._p.option_clicked_at = self._p.clock_ms
        if (x, y) == (3, 3):
            self._p.apply_clicked_at = self._p.clock_ms


class _UtSwitchPage:
    """사용자유형 전환 시나리오 FakePage — 준비 시점을 가짜 시계(ms)로 제어한다.

    wait_for_timeout 이 시계를 전진시키고 time.monotonic 를 그 시계로 patch(install_clock,
    _LogPage 선례)해 monotonic 상한 폴링이 실시간 낭비 없이 진행/소진된다.
    """

    def __init__(
        self,
        *,
        target: str = "회계",
        option_ready_ms: float = 0,
        display_delay_ms: float = 0,
        display_reflects: bool = True,
        reload_delay_ms: float = 0,
        avatar_delay_ms: float = 0,
        avatar_appears: bool = True,
    ) -> None:
        self.target = target
        self.option_ready_ms = option_ready_ms
        self.display_delay_ms = display_delay_ms
        self.display_reflects = display_reflects
        self.reload_delay_ms = reload_delay_ms
        self.avatar_delay_ms = avatar_delay_ms
        self.avatar_appears = avatar_appears
        self.clock_ms = 0.0
        self.clicks: list[tuple[int, int]] = []
        self.option_clicked_at: float | None = None
        self.apply_clicked_at: float | None = None
        self.marker_set = False
        self.mouse = _Mouse(self)

    def install_clock(self, monkeypatch) -> None:
        monkeypatch.setattr("nbkit.omnisol.auth.time.monotonic", lambda: self.clock_ms / 1_000)

    def _reloaded(self) -> bool:
        return (
            self.apply_clicked_at is not None
            and self.clock_ms >= self.apply_clicked_at + self.reload_delay_ms
        )

    async def wait_for_timeout(self, ms):
        self.clock_ms += ms

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.UT_DROPDOWN_BOX_JS:
            return {"x": 1, "y": 1}
        if js_src == js_lib.UT_OPTION_BOX_JS:
            return {"x": 2, "y": 2} if self.clock_ms >= self.option_ready_ms else None
        if js_src == js_lib.UT_DISPLAY_JS:
            if (
                self.display_reflects
                and self.option_clicked_at is not None
                and self.clock_ms >= self.option_clicked_at + self.display_delay_ms
            ):
                return f"{self.target}사용자"
            return "인사사용자(예외)"
        if js_src == js_lib.UT_APPLY_BOX_JS:
            return {"x": 3, "y": 3}
        if "__nbUtApplyMark = true" in js_src:
            self.marker_set = True
            return True
        if "__nbUtApplyMark === true" in js_src:
            return self.marker_set and not self._reloaded()
        if js_src == _SELECTOR_PRESENT_JS and arg == selectors.AVATAR:
            if not self.avatar_appears:
                return False
            return self._reloaded() and self.clock_ms >= (
                (self.apply_clicked_at or 0) + self.reload_delay_ms + self.avatar_delay_ms
            )
        if js_src == js_lib.NOTICE_POPUP_BOXES_JS:
            return None  # 공지 없음 — dismiss 는 관찰창(가짜 시계) 소진 후 no-op.
        if js_src == js_lib.USER_TYPE_READ_JS:
            return "?"
        return None


@pytest.fixture(autouse=True)
def _reset_latency():
    latency.reset()
    yield
    latency.reset()


# ── _switch_user_type_real: 옵션 렌더·선택 반영 폴링 ──────────────────────────────
async def test_switch_real_immediate_ready_is_fast(monkeypatch):
    """즉시 준비 = 빠른 통과 — 종전 고정 1s+1s 가 좌표 안정 확인 1폴(150ms) 수준으로 준다."""
    page = _UtSwitchPage()
    page.install_clock(monkeypatch)
    ok = await auth._switch_user_type_real(page, "회계")
    assert ok is True
    assert page.clicks == [(1, 1), (2, 2), (3, 3)]  # 드롭다운 → 옵션 → 변경적용.
    assert page.marker_set is True  # reload 감지 마커를 심고 변경적용을 눌렀다.
    assert page.clock_ms <= 450  # 종전 고정 2s 대비(좌표 안정 재확인 1폴만).


async def test_switch_real_waits_for_late_option_and_display(monkeypatch):
    """늦은 준비 = 대기 후 통과 — 옵션 리스트 렌더(600ms)·선택 반영(450ms)을 기다려 성공."""
    page = _UtSwitchPage(option_ready_ms=600, display_delay_ms=450)
    page.install_clock(monkeypatch)
    ok = await auth._switch_user_type_real(page, "회계")
    assert ok is True
    assert page.clicks == [(1, 1), (2, 2), (3, 3)]
    assert 1_000 <= page.clock_ms < 3_000  # 상한(1.5s+1.5s) 내에서 조건 충족 시점에 진행.


async def test_switch_real_false_when_display_never_reflects(monkeypatch):
    """미준비 = 실패 반환(변경적용 미클릭) — 상한 소진 후 False → attempts=2 재시도가 처리."""
    page = _UtSwitchPage(display_reflects=False)
    page.install_clock(monkeypatch)
    ok = await auth._switch_user_type_real(page, "회계")
    assert ok is False
    assert (2, 2) in page.clicks  # 옵션까지는 클릭했지만
    assert (3, 3) not in page.clicks  # 반영 미확인이면 변경적용을 누르지 않는다.
    assert page.clock_ms >= 1_500  # 표시 반영 상한을 실제로 관찰했다.


# ── _wait_reload_after_apply: 마커 소멸 → 아바타 재출현 ──────────────────────────
async def test_wait_reload_polls_marker_then_avatar(monkeypatch):
    """reload(800ms) + 아바타 렌더(700ms)를 조건 충족 즉시 통과 — networkidle 12s 소진 없음."""
    page = _UtSwitchPage(reload_delay_ms=800, avatar_delay_ms=700)
    page.install_clock(monkeypatch)
    page.marker_set = True
    page.apply_clicked_at = 0.0
    await auth._wait_reload_after_apply(page)
    assert 1_500 <= page.clock_ms < 4_000  # ≈ 실제 준비 시점(1.5s) — 종전 고정 ~16s 대비.


async def test_wait_reload_returns_at_cap_when_avatar_never_appears(monkeypatch):
    """아바타 미출현(전환 실패/셀렉터 변경)이어도 예외 없이 상한에서 반환 — 최종 판정은
    호출자의 패널 재오픈 + USER_TYPE_READ_JS 재독(더블체크)이 담당한다."""
    page = _UtSwitchPage(reload_delay_ms=300, avatar_appears=False)
    page.install_clock(monkeypatch)
    page.marker_set = True
    page.apply_clicked_at = 0.0
    await auth._wait_reload_after_apply(page)  # 예외 없이 반환해야 한다.
    assert page.clock_ms >= 12_000  # 상한(12s × factor 1.0)까지 관찰했다.


# ── switch_user_type 전체 경로 — 전환 성공(빠름) / 미반영 실패(재시도 후 에러) ─────
async def test_switch_user_type_full_path_fast(monkeypatch):
    """전환 실행 경로 전체가 고정 sleep 없이 조건 충족 시점에 완료된다(공지 관찰창 2s+2.5s
    는 유지 — 실측 근거가 있는 실시간 관찰창)."""
    page = _UtSwitchPage(reload_delay_ms=500, avatar_delay_ms=300)
    page.install_clock(monkeypatch)
    reads = iter(["인사사용자(예외)", "회계사용자"])

    async def _panel(p):
        return None

    async def _read(p):
        return next(reads)

    monkeypatch.setattr(auth, "open_user_panel", _panel)
    monkeypatch.setattr(auth, "read_current_user_type", _read)

    await auth.switch_user_type(page, "회계")
    assert (3, 3) in page.clicks  # 변경적용까지 실클릭.
    # 공지 관찰창(2s+2.5s, 유지) + 조건 폴링 합계가 종전 고정 시퀀스(~18s)의 절반 미만.
    assert page.clock_ms < 9_000


async def test_switch_user_type_raises_after_retries(monkeypatch):
    """미준비(전환 실클릭 실패 지속) = 기존 attempts=2 재시도 후 UserTypeError(동작 보존)."""
    page = _UtSwitchPage(display_reflects=False)
    page.install_clock(monkeypatch)

    async def _panel(p):
        return None

    async def _read(p):
        return "인사사용자(예외)"

    monkeypatch.setattr(auth, "open_user_panel", _panel)
    monkeypatch.setattr(auth, "read_current_user_type", _read)

    with pytest.raises(UserTypeError):
        await auth.switch_user_type(page, "회계", attempts=2)
