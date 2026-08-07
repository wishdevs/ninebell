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
from nbkit.omnisol import js_lib, latency, selectors, verify
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
        if not await js_click(page, selectors.BTN_LOOKUP):
            # 버튼 미발견(리스킨/화면 미로딩)은 폴링·재시도가 무의미한 구조 실패 — 종전엔 반환을
            # 버려 클릭이 안 나갔는데도 3회전 ~45s 명목 폴을 태운 뒤 '응답하지 않음'으로
            # 오진했다(2026-08-07 감사, voucher run_query 의 js_click 반환 확인과 동일 규율).
            await emit_step(emit, "query", "failed")
            raise GridError("조회 버튼을 찾지 못했습니다(화면 미로딩/버튼 변경 가능) — 조회를 실행하지 못했습니다.")
        # ⚠ 시간축 규율(2026-08-07): 종전 wait_for_timeout(1s)×15 명목 폴은 간격이 delay_scale
        # 로 축소돼 실관찰창이 붕괴한다 — 폴 대기는 실시간(verify.DEFAULT_SLEEP)으로 세고
        # 상한만 latency 배율(≤×4)로 확대한다(voucher_receivable._apply_popup 과 동일 패턴).
        waited = 0
        cap_ms = latency.budget_ms(QUERY_POLL_TRIES * 1_000)
        while waited < cap_ms:
            await verify.DEFAULT_SLEEP(1.0)
            waited += 1_000
            n = await page.evaluate(js_lib.ROWCOUNT_JS)
            if isinstance(n, int) and n > 0:
                rows = n
                break
            if waited == 9_000:  # 중간 상황 알림 + 화면 캡처(종전 9회차와 동일 시점).
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
