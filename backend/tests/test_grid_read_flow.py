"""nbkit.patterns.grid_read_flow.run_query 계약 — 브라우저 없이(2026-08-07 감사 회귀).

고정하는 계약:
  1. 조회 버튼 클릭(js_click)이 실패(버튼 미발견)하면 **즉시** 구조화 실패(GridError)로 끊는다 —
     종전엔 반환을 버려 클릭이 안 나갔는데도 ~45s 명목 폴을 태운 뒤 '응답하지 않음'으로 오진했다.
  2. 그리드 관찰 대기는 실시간 sleep 이다 — wait_for_timeout(delay_scale 축소 대상)이면
     느린 세션에서 관찰창이 붕괴해 정상 진행 중인 조회를 실패로 오판한다.
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import js_lib
from nbkit.patterns import grid_read_flow

pytestmark = pytest.mark.asyncio


class _QueryPage:
    """ROWCOUNT_JS 를 시퀀스로 응답(소진되면 마지막 값 유지)하는 페이크."""

    def __init__(self, rowcounts: list[int]) -> None:
        self._seq = list(rowcounts)
        self.evals = 0
        self.waits: list[int] = []

    async def evaluate(self, js_src, arg=None):
        assert js_src is js_lib.ROWCOUNT_JS, f"예상치 못한 evaluate: {str(js_src)[:60]}"
        self.evals += 1
        return self._seq.pop(0) if len(self._seq) > 1 else self._seq[0]

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


@pytest.fixture(autouse=True)
def _skip_selector_wait(monkeypatch):
    async def _ready(page, selector, timeout_ms=0):
        return None

    monkeypatch.setattr(grid_read_flow, "wait_for_selector", _ready)


async def test_run_query_fails_fast_when_lookup_button_missing(monkeypatch):
    async def _no_click(page, selector):
        return False

    monkeypatch.setattr(grid_read_flow, "js_click", _no_click)
    page = _QueryPage([0])
    with pytest.raises(grid_read_flow.GridError) as ei:
        await grid_read_flow.run_query(page)
    assert "버튼" in str(ei.value)
    assert page.evals == 0  # 클릭이 안 나갔는데 폴을 태우지 않는다(종전 ~45s 낭비).


async def test_run_query_polls_realtime_until_rows_arrive(monkeypatch):
    async def _click(page, selector):
        return True

    monkeypatch.setattr(grid_read_flow, "js_click", _click)
    page = _QueryPage([0, 0, 7])
    rows = await grid_read_flow.run_query(page)
    assert rows == 7
    assert page.waits == []  # 관찰 대기는 wait_for_timeout(delay_scale 축소 대상)이 아니다.
