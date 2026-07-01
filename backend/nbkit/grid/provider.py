"""GridProvider — 더존 dews/RealGrid 그리드에 대한 안전한 읽기 파사드.

RealGrid 는 캔버스라 DOM 추출이 안 통한다 → jQuery data 로 그리드 인스턴스를 잡아
``getRowCount``/``getJsonRows`` 를 호출한다(experience 문서 §2). 이 클래스는:

- 그리드 **인덱스**(0=마스터, 1=디테일, …)를 캡슐화하고,
- ``getJsonRows`` 의 **end-inclusive off-by-one 을 중앙에서 정규화**(:mod:`nbkit.grid.validation`)해
  호출자가 다시는 ``(0, n)`` vs ``(0, n-1)`` 로 헷갈리지 않게 한다.

Page 는 느슨하게(``Any``) 받는다. 그리드 접근 실패는 :class:`GridError` 로 승격한다.
"""

from __future__ import annotations

from typing import Any

from nbkit.browser.actions import safe_evaluate
from nbkit.grid import validation
from nbkit.omnisol import js_lib
from nbkit.omnisol.errors import GridError


class GridProvider:
    """단일 dews 그리드(``.dews-ui-grid`` 의 index 번째)에 대한 읽기 접근자."""

    def __init__(self, page: Any, grid_index: int = 0):
        self._page = page
        self._index = grid_index

    @property
    def index(self) -> int:
        return self._index

    async def get_row_count(self) -> int:
        """현재 rowCount. 그리드 미로드/접근 불가면 -1(호출자 폴링용)."""
        n = await safe_evaluate(
            self._page, js_lib.ROWCOUNT_BY_INDEX_JS, self._index, default=-1
        )
        try:
            return int(n)
        except (TypeError, ValueError):
            return -1

    async def get_rows(self, start: int = 0, count: int | None = None) -> list[dict]:
        """start 부터 count 개 행을 dict 리스트로 반환(off-by-one 자동 정규화).

        - ``count is None`` → start 부터 끝까지.
        - 내부적으로 rowCount 를 읽어 :func:`validation.normalize_range` 로
          ``(start, end_inclusive, take)`` 를 계산 → in-page ``getJsonRows(start, end_inclusive)``.
        - take==0 이면 빈 리스트. 그리드 접근 실패면 :class:`GridError`.
        """
        total = await self.get_row_count()
        if total < 0:
            raise GridError(f"그리드[{self._index}] 접근 실패(인스턴스 없음/미로드).")
        start_n, end_inclusive, take = validation.normalize_range(start, count, total)
        if take == 0:
            return []
        rows = await safe_evaluate(
            self._page,
            js_lib.GET_JSON_ROWS_JS,
            {"index": self._index, "start": start_n, "end": end_inclusive},
            default=None,
        )
        if rows is None:
            raise GridError(f"그리드[{self._index}] getJsonRows 실패.")
        return list(rows)

    async def get_all_rows(self) -> list[dict]:
        """그리드 전체 행. 대용량 그리드는 상위에서 페이지네이션 권장."""
        return await self.get_rows(0, None)
