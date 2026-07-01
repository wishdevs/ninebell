"""그리드 조회+수집 플로우 — read_grid_with_fallback(page, …).

두 부분:
1. **조회 재시도 루프**(run_query): 조회 버튼 클릭 → rowCount>0 될 때까지 폴링, 최대 3회
   재조회(시도당 ~15초). 그리드가 안 뜨면 명확한 타임아웃 :class:`GridError`(graph.py make_query_node).
2. **수집**: :class:`GridExtractor` 로 상위 N행 + 디테일(방법 A 병렬 → 실패 시 방법 B 키보드).

진행 이벤트(query/grid_read running·done·failed, 로그, 스냅샷)를 emit.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from nbkit.browser.actions import js_click
from nbkit.browser.waits import wait_for_selector
from nbkit.grid.strategies import CollectionStrategy, GridExtractor
from nbkit.omnisol import js_lib, selectors
from nbkit.omnisol.errors import GridError
from nbkit.patterns import EmitFn, emit_log, emit_shot, emit_step

QUERY_ATTEMPTS = 3
QUERY_POLL_TRIES = 15  # 시도당 폴링 횟수(≈초)


async def run_query(page: Any, *, emit: Optional[EmitFn] = None) -> int:
    """조회 버튼을 눌러 그리드가 채워질 때까지 폴링. 채워진 rowCount 반환.

    3회 재조회에도 그리드가 안 뜨면 :class:`GridError`(약 45초 타임아웃).
    """
    await emit_step(emit, "query", "running")
    t0 = time.monotonic()
    await wait_for_selector(page, selectors.BTN_LOOKUP, timeout_ms=10_000)
    rows = 0
    for attempt in range(1, QUERY_ATTEMPTS + 1):
        if attempt > 1:
            await emit_log(
                emit, f"조회 재시도 ({attempt}/{QUERY_ATTEMPTS}) — 그리드가 안 떠서 다시 조회합니다.", "warn"
            )
        await js_click(page, selectors.BTN_LOOKUP)
        for i in range(QUERY_POLL_TRIES):
            await page.wait_for_timeout(1_000)
            n = await page.evaluate(js_lib.ROWCOUNT_JS)
            if isinstance(n, int) and n > 0:
                rows = n
                break
            if i == 8:  # 중간 상황 알림 + 화면 캡처
                await emit_log(emit, f"조회 응답 대기 중… ({int(time.monotonic() - t0)}초 경과)", "info")
                await emit_shot(emit, page)
        if rows > 0:
            break
    if rows == 0:
        await emit_step(emit, "query", "failed")
        raise GridError(
            "조회가 응답하지 않습니다(약 45초 타임아웃). 더존 부하/지연일 수 있으니 잠시 후 다시 실행해 주세요."
        )
    await emit_log(emit, f"조회 완료 — {rows}건 조회됨.", "ok")
    await emit_step(emit, "query", "done", int((time.monotonic() - t0) * 1000))
    return rows


async def read_grid_with_fallback(
    page: Any,
    *,
    master_count: int,
    detail_service_url: str | None,
    master_id_field: str | None = "INVTRX_RSV_NO",
    strategy: CollectionStrategy = CollectionStrategy.AUTO,
    do_query: bool = True,
    master_index: int = 0,
    detail_index: int = 1,
    emit: Optional[EmitFn] = None,
) -> dict:
    """(옵션)조회 → 상위 master_count 마스터 + 디테일 수집. 원시 수집 dict 반환.

    반환: ``{"total", "masters", "details":[{"no","rows"}], "strategy"}``.
    표시용 컬럼 매핑/데이터셋 조립은 상위(에이전트)의 몫이다.
    """
    if do_query:
        await run_query(page, emit=emit)

    await emit_step(emit, "grid_read", "running")
    t0 = time.monotonic()
    extractor = GridExtractor(page, master_index=master_index, detail_index=detail_index)
    try:
        result = await extractor.extract(
            master_count=master_count,
            detail_service_url=detail_service_url,
            master_id_field=master_id_field,
            strategy=strategy,
        )
    except Exception:
        await emit_step(emit, "grid_read", "failed")
        raise
    await emit_log(
        emit,
        f"수집 완료 — 마스터 {len(result.get('masters', []))}행 (전략 {result.get('strategy')}).",
        "ok",
    )
    await emit_shot(emit, page)
    await emit_step(emit, "grid_read", "done", int((time.monotonic() - t0) * 1000))
    return result
