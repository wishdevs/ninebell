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
import time
from enum import Enum
from typing import Any

from nbkit.browser.actions import mouse_click, safe_evaluate
from nbkit.browser.frames import jiggle, press_arrow_down
from nbkit.grid import validation
from nbkit.grid.provider import GridProvider
from nbkit.omnisol import js_lib
from nbkit.omnisol.errors import GridError

logger = logging.getLogger("nbkit.grid.strategies")

DEFAULT_DWELL_MS = 1_500  # 방법 B 행당 정착 상한 기준(experience 실측 ~1.5s)
# 방법 B 디테일 정착은 고정 dwell 이 아니라 **조건 폴링**이다(느린 로드에서 직전 행 디테일이
# 현재 행에 붙는 무증상 오염 방지). 상한은 monotonic 실시간 — dwell_ms × 배수.
_DETAIL_POLL_INTERVAL_MS = 150
_DETAIL_SETTLE_CAP_MULT = 2  # 행당 폴링 상한 = dwell_ms × 2 (실측 1.5s 초과 로드 흡수)

# 첫 행 실클릭 좌표 — 기본 경로는 마스터 그리드 bbox 로 동적 계산(뷰포트 불문).
_GRID_HEADER_H = 34  # dews 그리드 헤더 높이(px) — 좌표 실측 상수(y = top+34+행idx*32+16)
_GRID_ROW_H = 32  # 행 높이(px)
_FIRST_ROW_X_MAX_OFFSET = 200  # 행 좌측 안쪽을 클릭(그리드 폭 절반 상한)
_LEGACY_FIRST_ROW_XY = (400, 330)  # 뷰포트 1600×1000 시절 검증 좌표 — bbox 실패 시 최후 폴백


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
        first_row_xy: tuple[int, int] | None = None,
        dwell_ms: int = DEFAULT_DWELL_MS,
    ) -> dict:
        """상위 ``master_count`` 마스터 + 각 디테일 수집.

        반환: ``{"total", "masters", "details":[{"no","rows"}], "strategy"}``.
        방법 B 에서 디테일 정착을 확정 못 한 행은 ``details`` 항목에 ``unverified: True``
        가 추가된다(상위에서 재시도/보정 — 조용한 빈값 아님).
        ``detail_service_url`` 이 있으면 방법 A(병렬 $.ajax)를 쓸 수 있다. AUTO 는 A 실패 시
        방법 B(키보드)로 폴백한다. detail_service_url 이 없으면 곧장 방법 B(또는 마스터-only).
        ``first_row_xy`` 는 방법 B 첫 행 실클릭 좌표 — 기본(None)은 마스터 그리드 bbox 로
        동적 계산하고, 명시 인자는 그대로 존중한다.
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

    async def _resolve_first_row_xy(self) -> tuple[int, int]:
        """방법 B 첫 행 실클릭 좌표를 마스터 그리드 bbox 로 동적 계산(뷰포트 불문).

        (left+안쪽 오프셋, top+헤더높이+행높이/2). 고정 좌표 기본값은 어느 뷰포트 기준인지
        불명확한 채 다른 뷰포트(라이브 1920×1200)에서 빗나갈 수 있어 bbox 계산이 기본 경로다.
        bbox 를 못 읽으면 구 검증 좌표(1600×1000 기준)로 최후 폴백.
        """
        rect = await safe_evaluate(
            self._page, js_lib.GRID_RECT_BY_INDEX_JS, self._master_index, default=None
        )
        if not rect:
            return _LEGACY_FIRST_ROW_XY
        x = int(rect["x"] + min(rect["width"] / 2, _FIRST_ROW_X_MAX_OFFSET))
        y = int(rect["y"] + _GRID_HEADER_H + _GRID_ROW_H / 2)
        return (x, y)

    async def _settle_detail(
        self,
        detail_p: GridProvider,
        master_id_field: str | None,
        expected: Any,
        baseline: int,
        *,
        cap_ms: int,
        interval_ms: int = _DETAIL_POLL_INTERVAL_MS,
    ) -> tuple[list[dict], bool]:
        """디테일 그리드가 '현재 마스터 행의 것'으로 정착할 때까지 조건 폴링.

        반환 ``(rows, verified)``. 판정(우선순위):
        1. **식별 필드 조인** — 디테일 첫 행의 ``master_id_field`` 가 ``expected`` 와 일치하면
           확정(전량 읽고 첫 행 재확인). 불일치는 직전 행 디테일이 남은 것 — 그 rows 는
           절대 돌려주지 않는다(무증상 오염 방지).
        2. **rowcount 변화+안정** — 조인 불가(필드 없음·0행·id 없음)일 때, 트리거 전
           ``baseline`` 대비 변화가 관측된 뒤 2회 연속 동일하면 정착으로 본다
           (codepicker._wait_picker_rows_stable 패턴, 상한은 monotonic 실시간).
        상한 소진 시 ``(best-effort rows, False)`` — 단 조인 불일치로 끝났으면 ``([], False)``.
        """
        t0 = time.monotonic()
        prev: int | None = None
        changed = False
        join_mismatch = False
        while (time.monotonic() - t0) * 1000 < cap_ms:
            await self._page.wait_for_timeout(interval_ms)
            n = await detail_p.get_row_count()
            if n < 0:  # 전환 중 순간 미접근 — baseline 이 유효했다면 그 자체가 변화 증거.
                changed = changed or baseline >= 0
                prev = None
                continue
            if n != baseline:
                changed = True
            # 1) 식별 필드 조인 — 행이 있고 필드가 실재할 때만 성립.
            if master_id_field and expected not in (None, "") and n > 0:
                try:
                    probe = await detail_p.get_rows(0, 1)
                except GridError:
                    prev = n
                    continue
                if probe and master_id_field in probe[0]:
                    if str(probe[0].get(master_id_field)) == str(expected):
                        try:
                            rows = await detail_p.get_all_rows()
                        except GridError:
                            prev = n
                            continue
                        # 전량 읽는 사이 갱신됐을 수 있어 첫 행을 재확인한다.
                        if rows and str(rows[0].get(master_id_field)) != str(expected):
                            join_mismatch = True
                            prev = n
                            continue
                        return rows, True
                    join_mismatch = True  # 직전 행 디테일이 아직 남음 → 계속 대기
                    prev = n
                    continue
            # 2) rowcount 변화+안정(조인 불가 경로).
            if changed and prev == n:
                try:
                    return await detail_p.get_all_rows(), True
                except GridError:
                    prev = n
                    continue
            prev = n
        if join_mismatch:
            return [], False  # 직전 행 디테일로 확정 — 오염 rows 전달 금지
        try:
            return await detail_p.get_all_rows(), False
        except GridError:
            return [], False

    async def _keyboard_fallback(
        self,
        master_count: int,
        master_id_field: str | None,
        first_row_xy: tuple[int, int] | None,
        dwell_ms: int,
    ) -> dict:
        """방법 B — trusted ArrowDown 으로 마스터 순회하며 디테일 그리드를 직접 읽는다.

        setCurrent(앵커) → 첫 행 실클릭(포커스+행0 로드) → 행마다 [ArrowDown → 조건 폴링].
        느리지만 캐시·서명·가로채기와 무관해 가장 견고(experience §3-B).

        행당 고정 dwell 은 폐기 — 로드가 dwell 을 넘으면 직전 행 디테일이 현재 행에 붙는
        무증상 오염이 있어, :meth:`_settle_detail` 조건 폴링으로 정착을 확인한다. 미정착
        행은 jiggle(ArrowUp→ArrowDown, OMNISOL_NOTES §3-B 복구 동작)로 재앵커링 후 1회
        재시도하고, 그래도 확정 못 하면 ``unverified: True`` 로 명시 마킹해 올린다.
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
        xy = first_row_xy if first_row_xy is not None else await self._resolve_first_row_xy()
        cap_ms = max(int(dwell_ms), 1) * _DETAIL_SETTLE_CAP_MULT

        details: list[dict] = []
        for i, m in enumerate(masters):
            expected = m.get(master_id_field) if master_id_field else None
            baseline = await detail_p.get_row_count()  # 트리거 전 rowcount(변화 감지 기준)
            if i == 0:
                await mouse_click(self._page, xy[0], xy[1])
            else:
                await press_arrow_down(self._page)  # trusted → 디테일 자동 갱신
            rows, verified = await self._settle_detail(
                detail_p, master_id_field, expected, baseline, cap_ms=cap_ms
            )
            if not verified:
                # 미정착 → jiggle 재앵커링(재시도 기준 rowcount 를 다시 잡는다).
                logger.warning("방법 B 행 %s 디테일 미정착 — jiggle 재앵커링 후 재시도", i)
                baseline2 = await detail_p.get_row_count()
                await jiggle(self._page)
                # jiggle 은 최상단(행0)에서 커서를 이탈시킨다 — ArrowUp 은 무효(행 유지)인데
                # ArrowDown 은 실동작해 행1 로 밀리고, 이후 전 행 수집이 한 행씩 밀린다
                # (조인 불가 그리드에선 무증상 오염). setCurrent 로 행 i 에 명시 재앵커해
                # 정렬을 복원한다(앵커 전용 — 디테일 로드는 트리거하지 않음, js_lib 주석 참조).
                await safe_evaluate(
                    self._page,
                    js_lib.SET_CURRENT_BY_INDEX_JS,
                    {"index": self._master_index, "itemIndex": i},
                    default=False,
                )
                rows, verified = await self._settle_detail(
                    detail_p, master_id_field, expected, baseline2, cap_ms=cap_ms
                )
            no = expected if master_id_field else i
            entry: dict = {"no": no, "rows": rows}
            if not verified:
                entry["unverified"] = True  # 상위에서 재시도/보정 — 조용한 빈값 금지
                logger.warning("방법 B 행 %s(no=%s) 디테일 확정 실패 — unverified 마킹", i, no)
            details.append(entry)
        return {
            "total": len(masters),
            "masters": masters,
            "details": details,
            "strategy": CollectionStrategy.KEYBOARD_FALLBACK.value,
        }
