"""수집 전략 — 병렬 함수호출(빠름) vs 키보드 폴백(견고), AUTO 로 자동 선택.

collection-strategies.md 결론:
- **PARALLEL_AJAX**(방법 A, 권장): 마스터는 ``getJsonRows`` 로 즉시, 디테일은 앱 dataSource
  transport URL 로 ``$.ajax`` 병렬(앱이 인증 JWT 자동주입 → 가로채기 아님). 20행 ~150ms.
- **KEYBOARD_FALLBACK**(방법 B, 폴백): 앱이 함수호출을 막았을 때. **실제 ArrowDown(trusted)**
  으로 마스터를 옮기면 앱이 디테일을 렌더 → 디테일 그리드를 직접 읽는다(experience §3-B).
- **AUTO**: A 를 먼저 시도, 실패하면 B 로 폴백.

⚠ 현재 PARALLEL_AJAX 의 in-page JS 는 검증된 **BOM 마스터-디테일 형태**(_uid/INVTRX_RSV_NO/
  close_yn)를 대상으로 한다(:func:`nbkit.omnisol.js_lib.collect_master_detail_js`). 다른 화면
  형태가 생기면 그 빌더를 확장한다.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from nbkit.browser.actions import mouse_click, safe_evaluate
from nbkit.browser.frames import press_arrow_down
from nbkit.grid import validation
from nbkit.grid.provider import GridProvider
from nbkit.omnisol import js_lib
from nbkit.omnisol.errors import GridError

logger = logging.getLogger("nbkit.grid.strategies")

DEFAULT_DWELL_MS = 1_500  # 방법 B 행당 정착 대기(experience 실측 ~1.5s)


class CollectionStrategy(str, Enum):
    """마스터-디테일 수집 전략."""

    PARALLEL_AJAX = "parallel_ajax"  # 방법 A — 함수호출 병렬(빠름)
    KEYBOARD_FALLBACK = "keyboard_fallback"  # 방법 B — trusted 키보드(견고)
    AUTO = "auto"  # A 시도 → 실패 시 B


class GridExtractor:
    """조회 완료 상태의 마스터-디테일 그리드에서 상위 N행 + 각 디테일을 수집."""

    def __init__(self, page: Any, *, master_index: int = 0, detail_index: int = 1):
        self._page = page
        self._master_index = master_index
        self._detail_index = detail_index

    async def extract(
        self,
        *,
        master_count: int,
        detail_service_url: str | None,
        master_id_field: str | None = "INVTRX_RSV_NO",
        strategy: CollectionStrategy = CollectionStrategy.AUTO,
        first_row_xy: tuple[int, int] = (400, 330),
        dwell_ms: int = DEFAULT_DWELL_MS,
    ) -> dict:
        """상위 ``master_count`` 마스터 + 각 디테일 수집.

        반환: ``{"total", "masters", "details":[{"no","rows"}], "strategy"}``.
        ``detail_service_url`` 이 있으면 방법 A(병렬 $.ajax)를 쓸 수 있다. AUTO 는 A 실패 시
        방법 B(키보드)로 폴백한다. detail_service_url 이 없으면 곧장 방법 B(또는 마스터-only).
        """
        if strategy is CollectionStrategy.PARALLEL_AJAX:
            return await self._parallel_ajax(master_count, detail_service_url)
        if strategy is CollectionStrategy.KEYBOARD_FALLBACK:
            return await self._keyboard_fallback(
                master_count, master_id_field, first_row_xy, dwell_ms
            )
        # AUTO
        if detail_service_url:
            try:
                return await self._parallel_ajax(master_count, detail_service_url)
            except Exception as exc:  # noqa: BLE001 — 앱이 함수호출 차단 등 → 폴백
                logger.warning("방법 A(병렬) 실패(%s) — 방법 B(키보드) 폴백", exc)
        return await self._keyboard_fallback(
            master_count, master_id_field, first_row_xy, dwell_ms
        )

    async def _parallel_ajax(self, master_count: int, detail_service_url: str | None) -> dict:
        """방법 A — collect JS 한 번으로 마스터 일괄 + 디테일 병렬. off-by-one 검증."""
        if not detail_service_url:
            raise GridError("방법 A 는 detail_service_url 이 필요합니다.")
        raw = await safe_evaluate(
            self._page,
            js_lib.collect_master_detail_js(detail_service_url),
            master_count,
            default=None,
        )
        if not raw:
            raise GridError("방법 A 수집 실패(그리드 인스턴스 접근 불가).")
        total = int(raw.get("total", 0))
        masters = list(raw.get("masters", []))
        # 정규화 검증: JS 가 take=min(limit,total) 로 클램프하므로 기대치와 일치해야 함.
        expected = validation.clamp_count(master_count, total)
        validation.validate_master_count(expected, len(masters))
        return {
            "total": total,
            "masters": masters,
            "details": list(raw.get("details", [])),
            "strategy": CollectionStrategy.PARALLEL_AJAX.value,
        }

    async def _keyboard_fallback(
        self,
        master_count: int,
        master_id_field: str | None,
        first_row_xy: tuple[int, int],
        dwell_ms: int,
    ) -> dict:
        """방법 B — trusted ArrowDown 으로 마스터 순회하며 디테일 그리드를 직접 읽는다.

        setCurrent(앵커) → 첫 행 실클릭(포커스+행0 로드) → 행마다 [디테일 읽기 → ArrowDown].
        느리지만 캐시·서명·가로채기와 무관해 가장 견고(experience §3-B).
        """
        master_p = GridProvider(self._page, self._master_index)
        detail_p = GridProvider(self._page, self._detail_index)
        masters = await master_p.get_rows(0, master_count)
        # 최상단 앵커(디테일은 아직 안 바뀜) + 첫 행 실클릭으로 포커스/행0 로드.
        await safe_evaluate(
            self._page,
            js_lib.SET_CURRENT_BY_INDEX_JS,
            {"index": self._master_index, "itemIndex": 0},
            default=False,
        )
        await mouse_click(self._page, first_row_xy[0], first_row_xy[1])
        await self._page.wait_for_timeout(dwell_ms)

        details: list[dict] = []
        for i, m in enumerate(masters):
            if i > 0:
                await press_arrow_down(self._page)  # trusted → 디테일 자동 갱신
                await self._page.wait_for_timeout(dwell_ms)
            no = m.get(master_id_field) if master_id_field else i
            try:
                rows = await detail_p.get_all_rows()
            except GridError:
                rows = []  # 이 행 디테일 미로드 — 상위에서 재시도/보정
            details.append({"no": no, "rows": rows})
        return {
            "total": len(masters),
            "masters": masters,
            "details": details,
            "strategy": CollectionStrategy.KEYBOARD_FALLBACK.value,
        }
