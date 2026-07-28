"""nbkit.omnisol.modals.dismiss_notice_popup — 로그인 직후 공지 레이어 팝업 닫기(전 에이전트 공통).

'하루동안 보지 않기'(#close-today-chk) 체크 후 '닫기'(#notice-dialog-close). 팝업이 없으면 no-op.
appear_cap_ms=0 이면 대기 없이 1회만 확인(피커 클릭 직전 just-in-time 재확인용).
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import js_lib
from nbkit.omnisol.modals import dismiss_notice_popup

pytestmark = pytest.mark.asyncio


class _Mouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    async def click(self, x, y):
        self.clicks.append((x, y))


class _Page:
    """NOTICE_POPUP_BOXES_JS 호출마다 seq 를 순서대로 돌려주는 스텁.

    wait_for_timeout 은 가짜 실시간 시계(clock_ms)를 요청 ms 만큼 진행시킨다 — dismiss 의
    상한 판정이 time.monotonic 실시간이라(delay_scale 무관), 테스트도 실시간 경과를 시뮬레이션
    해야 상한 소진 경로를 검증할 수 있다. modals.time.monotonic 를 이 시계로 monkeypatch.
    """

    def __init__(self, boxes_seq) -> None:
        self._seq = list(boxes_seq)
        self.mouse = _Mouse()
        self.evals = 0
        self.clock_ms = 0.0

    async def evaluate(self, js_src, arg=None):
        assert js_src == js_lib.NOTICE_POPUP_BOXES_JS
        self.evals += 1
        return self._seq.pop(0) if self._seq else None

    async def wait_for_timeout(self, ms):
        self.clock_ms += ms  # 가짜 실시간 진행(스케일 무관 — 스텁은 delay_scale 미적용).

    def install_clock(self, monkeypatch) -> None:
        monkeypatch.setattr("nbkit.omnisol.modals.time.monotonic", lambda: self.clock_ms / 1_000)


async def test_present_checks_today_then_closes_verified():
    unchecked = {"checkbox": {"x": 40, "y": 50}, "close": {"x": 60, "y": 50}, "checked": False}
    checked = {**unchecked, "checked": True}
    # 표시(미체크) → 체크 클릭 후 재평가(체크 확인) → 닫기 클릭 후 재평가(소멸 = 닫힘 검증).
    page = _Page([unchecked, checked, None])
    assert await dismiss_notice_popup(page) is True
    assert page.mouse.clicks == [(40, 50), (60, 50)]  # '하루동안 보지 않기' → '닫기'


async def test_absent_is_noop_single_check():
    page = _Page([None])
    assert await dismiss_notice_popup(page, appear_cap_ms=0) is False
    assert page.mouse.clicks == []
    assert page.evals == 1  # appear_cap_ms=0 → 대기 없이 1회만.


async def test_already_checked_only_closes():
    boxes = {"checkbox": {"x": 40, "y": 50}, "close": {"x": 60, "y": 50}, "checked": True}
    page = _Page([boxes, None])  # 체크 스킵 → 닫기 → 소멸 검증.
    assert await dismiss_notice_popup(page) is True
    assert page.mouse.clicks == [(60, 50)]  # 체크 스킵, 닫기만


async def test_close_miss_retries_until_gone():
    """닫기 클릭이 빗나가 팝업이 남으면(발사 후 미검증 결함 재현) 좌표 재평가 후 재클릭한다."""
    checked = {"checkbox": {"x": 40, "y": 50}, "close": {"x": 60, "y": 50}, "checked": True}
    moved = {**checked, "close": {"x": 62, "y": 52}}  # 애니메이션으로 좌표 이동 상황.
    page = _Page([checked, moved, None])  # 1차 닫기 후에도 잔존 → 재평가 좌표로 2차 → 소멸.
    assert await dismiss_notice_popup(page) is True
    assert page.mouse.clicks == [(60, 50), (62, 52)]  # 2차 클릭은 재평가된 좌표.


async def test_close_never_disappears_gives_up_at_cap(monkeypatch):
    """닫기 상한(close_cap_ms) 소진 시 False — 무한 대기 금지, 후속 JIT 방어에 위임.

    상한은 monotonic 실시간이라 가짜 시계로 경과를 시뮬레이션한다(닫기 폴 400ms 씩 진행).
    """
    checked = {"checkbox": {"x": 40, "y": 50}, "close": {"x": 60, "y": 50}, "checked": True}
    page = _Page([checked] * 10)  # 절대 안 사라짐.
    page.install_clock(monkeypatch)
    assert await dismiss_notice_popup(page, close_cap_ms=800) is False
    assert page.mouse.clicks == [(60, 50), (60, 50)]  # 400ms×2 = 상한 도달.


async def test_checkbox_miss_retries_then_closes():
    """체크 클릭이 빗나가면 checked 실측으로 감지해 재클릭 후 닫기까지 완료한다."""
    unchecked = {"checkbox": {"x": 40, "y": 50}, "close": {"x": 60, "y": 50}, "checked": False}
    checked = {**unchecked, "checked": True}
    page = _Page([unchecked, unchecked, checked, None])  # 1차 체크 빗나감 → 2차 성공 → 닫기.
    assert await dismiss_notice_popup(page) is True
    assert page.mouse.clicks == [(40, 50), (40, 50), (60, 50)]


async def test_evaluate_error_is_swallowed():
    class _Boom:
        mouse = _Mouse()

        async def evaluate(self, js_src, arg=None):
            raise RuntimeError("page gone")

        async def wait_for_timeout(self, ms):
            return None

    assert await dismiss_notice_popup(_Boom()) is False  # 로그인 자체를 막지 않는다
