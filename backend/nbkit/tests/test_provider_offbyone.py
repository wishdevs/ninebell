"""GridProvider off-by-one 정규화 — FakePage 로 라이브 브라우저 없이 end-inclusive 검증.

실제 RealGrid getJsonRows(start, end) 의 **end-inclusive** 계약을 흉내내는 FakePage 로,
GridProvider.get_rows 가 절대 21행(off-by-one)을 반환하지 않고 정확히 요청 수만 주는지 확인.
"""

from __future__ import annotations

import pytest

from nbkit.grid.provider import GridProvider
from nbkit.omnisol import js_lib
from nbkit.omnisol.errors import GridError


class FakeGridPage:
    """getJsonRows(start, end) 를 end-inclusive 로 흉내내는 최소 Page 스텁."""

    def __init__(self, total: int):
        self._data = [{"id": i} for i in range(total)]

    async def evaluate(self, script, arg=None):
        if script == js_lib.ROWCOUNT_BY_INDEX_JS:
            return len(self._data)
        if script == js_lib.GET_JSON_ROWS_JS:
            start, end = arg["start"], arg["end"]  # end 는 INCLUSIVE
            if end < start:
                return []
            return self._data[start : end + 1]
        raise AssertionError(f"예상치 못한 스크립트 호출: {script[:40]}")


class BrokenGridPage:
    """그리드 인스턴스 접근 실패(-1) 를 흉내내는 스텁."""

    async def evaluate(self, script, arg=None):
        if script == js_lib.ROWCOUNT_BY_INDEX_JS:
            return -1
        return None


async def test_get_rows_returns_exactly_requested_not_off_by_one():
    page = FakeGridPage(total=50)
    provider = GridProvider(page, grid_index=0)
    rows = await provider.get_rows(0, 20)
    assert len(rows) == 20  # 21 아님!
    assert rows[0]["id"] == 0
    assert rows[-1]["id"] == 19  # end-inclusive 정규화 검증


async def test_get_rows_clamps_to_total():
    page = FakeGridPage(total=12)
    provider = GridProvider(page)
    rows = await provider.get_rows(0, 20)
    assert len(rows) == 12


async def test_get_all_rows():
    page = FakeGridPage(total=7)
    provider = GridProvider(page)
    rows = await provider.get_all_rows()
    assert [r["id"] for r in rows] == list(range(7))


async def test_get_rows_start_offset():
    page = FakeGridPage(total=30)
    provider = GridProvider(page)
    rows = await provider.get_rows(10, 5)
    assert [r["id"] for r in rows] == [10, 11, 12, 13, 14]


async def test_get_row_count():
    provider = GridProvider(FakeGridPage(total=42))
    assert await provider.get_row_count() == 42


async def test_get_rows_raises_griderror_on_broken_grid():
    provider = GridProvider(BrokenGridPage())
    with pytest.raises(GridError):
        await provider.get_rows(0, 10)
