"""단계별 예상 소요시간(expectedMs) 계산 — 최근 성공 런 logs 실측 평균.

agent_runs.logs 의 단계 프레임({ts, step, status})에서 running→done ts 차이를 단계
소요로 본다(파싱은 e2e/smoke_cycle._analyze_logs 와 동일: running ts 를 pending 에
넣고 종료 프레임에서 뺀다). 최근 성공 런 limit 개의 step key 별 평균(int ms)을
반환하며, 상세 API(GET /agents/{id})의 ETA 타임라인 데이터 소스다.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun

# 인프로세스 TTL 캐시 — 상세 페이지를 열 때마다 최근 런 20개 logs 파싱을 반복하지
# 않는다. 키는 workflow_id, 값은 (기록 시각 monotonic, 결과 dict).
_CACHE_TTL_SEC = 300.0
_cache: dict[str, tuple[float, dict[str, int]]] = {}


def _run_step_ms(logs: list | None) -> dict[str, int]:
    """한 런의 logs 프레임 → step key 별 총 소요 ms.

    재시도로 같은 step 이 한 런에 여러 번 나오면(예: save 재시도로 menu_nav 재진입)
    **런 내 합산**한다 — 개별 발생 평균보다 사용자가 체감하는 '그 단계에 머문 총
    시간'에 가깝기 때문. 성공 런 안의 failed 프레임(재시도 전 실패)도 그 단계에
    머문 시간이므로 done 과 동일하게 구간을 닫아 합산한다.
    """
    pending: dict[str, int] = {}
    totals: dict[str, int] = {}
    for e in logs or []:
        if not isinstance(e, dict):
            continue
        ts, step, st = e.get("ts"), e.get("step"), e.get("status")
        if not step:
            continue
        if st == "running" and isinstance(ts, int):
            pending[step] = ts
        elif st in ("done", "failed"):
            start = pending.pop(step, None)
            if isinstance(start, int) and isinstance(ts, int) and ts >= start:
                totals[step] = totals.get(step, 0) + (ts - start)
    return totals


async def expected_step_ms(
    db: AsyncSession, workflow_id: str, *, limit: int = 20
) -> dict[str, int]:
    """workflow_id 의 최근 성공 런 limit 개에서 step key 별 평균 ms 를 계산한다.

    logs 가 없거나 단계 프레임이 파싱되지 않는 런은 건너뛴다. 표본이 없으면 빈 dict.
    """
    now = time.monotonic()
    hit = _cache.get(workflow_id)
    if hit is not None and now - hit[0] < _CACHE_TTL_SEC:
        return hit[1]

    rows = await db.execute(
        select(AgentRun.logs)
        .where(AgentRun.agent_id == workflow_id, AgentRun.status == "succeeded")
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
    )
    sums: dict[str, int] = {}
    counts: dict[str, int] = {}
    for logs in rows.scalars():
        per_run = _run_step_ms(logs)
        if not per_run:
            continue  # logs 없음/파싱 불가 런은 표본에서 제외.
        for step, ms in per_run.items():
            sums[step] = sums.get(step, 0) + ms
            counts[step] = counts.get(step, 0) + 1

    result = {step: sums[step] // counts[step] for step in sums}
    _cache[workflow_id] = (now, result)
    return result
