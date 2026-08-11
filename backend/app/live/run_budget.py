"""런 전역 활동 시간 예산 추적기 — run_id 키의 프로세스 전역 레지스트리.

정책: 예산은 **HITL 대기 시간을 제외한 활동 시간** 기준이다. 사용자가 그리드/채팅 응답을
오래 고민하는 것은 정당(턴당 hitl_timeout_s 상한이 별도로 있음) — 자동화 구간(브라우저
조작·LLM 호출 등)이 무한히 오래 도는 것만 제한한다. HITL 대기 블로킹 구간의 앞뒤에서
`pause`/`resume` 이 호출되며(app.live.hitl 의 예산 일시정지 큐), 중첩 안전(카운터)이다.

`app.live.hitl` 의 큐 레지스트리와 동일한 인프로세스 dict 패턴(동일 이벤트루프 전제).
시계는 monotonic 기준 — 테스트는 `_now` 를 monkeypatch 해 가짜 시계를 주입한다.

소비자: `app.live.runner` 의 워치독이 `start`/`active_elapsed`/`clear` 를 쓰고,
`app.live.hitl` 이 HITL 대기 구간에서 `pause`/`resume` 을 쓴다.

⚠ 한계(반저장 위험): 예산 초과 시 러너 워치독이 그래프 태스크를 cancel 하는데, 이는
사용자 취소(cancel)와 동일하게 ERP 저장 확정 구간 한가운데를 자를 수 있다(현재
asyncio.shield 미도입 상태 — 반저장 가능). 저장 확정 구간에 shield 를 도입할 때
이 워치독의 cancel 경로도 함께 shield 를 존중하도록 개선해야 한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


def _now() -> float:
    """monotonic 시계 간접층 — 테스트에서 가짜 시계로 대체한다."""
    return time.monotonic()


@dataclass
class _BudgetState:
    """런 하나의 활동 시간 상태.

    accumulated: pause 시점까지 확정된 활동 시간 누적(초).
    active_since: 현재 활동 구간의 시작(monotonic). pause 중이면 None.
    pause_depth: 중첩 pause 카운터 — 0 으로 돌아올 때만 활동 재개.
    """

    accumulated: float
    active_since: float | None
    pause_depth: int


# run_id → 예산 상태. runner 가 start/clear 하고, hitl 이 pause/resume 한다.
_budgets: dict[str, _BudgetState] = {}


def start(run_id: str) -> None:
    """예산 추적 시작 — 활동 구간이 지금부터 흐른다(중복 start 는 리셋)."""
    _budgets[run_id] = _BudgetState(accumulated=0.0, active_since=_now(), pause_depth=0)


def pause(run_id: str | None) -> None:
    """활동 시간 일시정지(HITL 대기 진입) — 중첩 안전. 미등록 run 은 no-op."""
    st = _budgets.get(run_id) if run_id else None
    if st is None:
        return
    st.pause_depth += 1
    if st.pause_depth == 1 and st.active_since is not None:
        st.accumulated += _now() - st.active_since
        st.active_since = None


def resume(run_id: str | None) -> None:
    """활동 시간 재개(HITL 대기 종료) — 최심 pause 가 모두 풀릴 때만 재개. 미등록 run 은 no-op."""
    st = _budgets.get(run_id) if run_id else None
    if st is None:
        return
    if st.pause_depth > 0:
        st.pause_depth -= 1
        if st.pause_depth == 0:
            st.active_since = _now()


def active_elapsed(run_id: str | None) -> float:
    """누적 활동 시간(초) — pause 중 구간은 제외. 미등록 run 은 0.0."""
    st = _budgets.get(run_id) if run_id else None
    if st is None:
        return 0.0
    total = st.accumulated
    if st.active_since is not None:
        total += _now() - st.active_since
    return total


def clear(run_id: str | None) -> None:
    """추적 종료(런 종료·취소·예외 공통 — runner finally 에서 보장). 멱등."""
    if run_id:
        _budgets.pop(run_id, None)
