"""HITL(사용자 개입) 큐 — 흐름을 멈추고 사용자 응답을 기다린다.

흐름(그래프 노드)은 decision_id 로 큐를 만들어 대기하고, `/runs/hitl` 엔드포인트가
`resolve_hitl` 로 그 큐에 응답을 넣어 흐름을 깨운다(동일 이벤트루프·인프로세스 전제).
소유권(`_hitl_owner`)은 LiveSession 이 hitl 이벤트를 볼 때 `set_hitl_owner` 로 등록하고,
`/runs/hitl` 이 `hitl_owner` 로 검증해 다른 사용자의 개입을 차단한다.

ninebell-bak `erp/graph.py` 의 HITL 큐 부분을 워크플로우 무관 모듈로 분리 이식했다.
"""

from __future__ import annotations

import asyncio
import uuid

from app.config import get_settings

from . import run_budget


class _BudgetPausedQueue(asyncio.Queue):
    """get() 대기 동안 런 활동 시간 예산을 일시정지하는 HITL 큐.

    런 전역 예산(run_budget)은 HITL 대기 시간을 제외한 **활동 시간** 기준이다. 노드는
    이 큐를 `asyncio.wait_for(q.get(), ...)` 로 그대로 쓰므로(계약 불변), 실제 사용자
    입력을 기다리는 블로킹 구간이 정확히 pause/resume 으로 감싸진다. 타임아웃/취소로
    get() 이 중단돼도 finally 로 resume 이 보장된다(run_budget 은 중첩 안전).
    run_id 미바인딩(스크립트/익명) 큐는 순수 asyncio.Queue 와 동일하게 동작한다.
    """

    def __init__(self, run_id: str | None = None) -> None:
        super().__init__()
        self._budget_run_id = run_id

    async def get(self):  # noqa: ANN201 — asyncio.Queue.get 시그니처 유지
        if not self._budget_run_id:
            return await super().get()
        run_budget.pause(self._budget_run_id)
        try:
            return await super().get()
        finally:
            run_budget.resume(self._budget_run_id)


# decision_id → 대기 큐. 노드가 만들고, resolve_hitl 이 넣고, 노드가 pop 한다.
_hitl_queues: dict[str, asyncio.Queue] = {}
# decision_id → owner(세션 사용자 식별자). 값이 있으면 그 사용자만 resolve 가능.
_hitl_owner: dict[str, str] = {}
# decision_id → run_id(세션/런 id). 값이 있으면 `/runs/hitl` 의 runId 와 교차검증한다.
_hitl_run_id: dict[str, str] = {}


def open_hitl_channel(
    decision_id: str,
    *,
    owner: str | None = None,
    run_id: str | None = None,
) -> asyncio.Queue:
    """지속(멀티턴) HITL 큐 등록 — 대화형 노드용.

    `wait_hitl`(단발)과 달리 노드 수명 동안 같은 decision_id 로 큐를 유지해, 도구 실행 등
    턴 사이 공백에도 사용자 메시지가 유실되지 않고 큐잉된다. 반드시 `close_hitl_channel` 로 정리.
    소유권(`owner`)·런바인딩(`run_id`)은 채널 오픈 시점에 등록해, LiveSession 이 hitl 프레임을
    관찰하기 전 `/runs/hitl` 이 소유권 검사를 건너뛰던 레이스 창을 없앤다. falsy 면 미등록
    (스크립트/익명 경로 — session 펌프가 프레임 관찰 시 폴백 등록).

    반환 큐는 get() 대기 동안 런 활동 시간 예산을 일시정지한다(HITL 대기 제외 정책 —
    `_BudgetPausedQueue`). 노드 쪽 소비 계약(`asyncio.wait_for(q.get(), ...)`)은 불변.
    """
    q: asyncio.Queue = _BudgetPausedQueue(run_id)
    _hitl_queues[decision_id] = q
    if owner:
        _hitl_owner[decision_id] = owner
    if run_id:
        _hitl_run_id[decision_id] = run_id
    return q


def close_hitl_channel(decision_id: str) -> None:
    """`open_hitl_channel` 로 연 채널 정리(큐·소유권·런바인딩 제거)."""
    _hitl_queues.pop(decision_id, None)
    _hitl_owner.pop(decision_id, None)
    _hitl_run_id.pop(decision_id, None)


def set_hitl_owner(decision_id: str, owner: str | None) -> None:
    """이 개입의 소유자를 등록(옵션 A 격리). owner 가 falsy 면 개방(스크립트 경로).

    이미 채널 오픈 시점에 소유자가 바인딩됐으면 덮어쓰지 않는다(레이스 창은 오픈 시점에 이미
    닫힘). 소유자 미바인딩(익명/스크립트) 세션에서만 LiveSession 이 프레임 관찰 시 폴백 등록한다.
    """
    if owner and decision_id not in _hitl_owner:
        _hitl_owner[decision_id] = owner


def hitl_owner(decision_id: str) -> str | None:
    return _hitl_owner.get(decision_id)


def hitl_run_id(decision_id: str) -> str | None:
    return _hitl_run_id.get(decision_id)


def resolve_hitl(decision_id: str, payload: dict) -> bool:
    """대기 중인 흐름에 사용자 응답 전달. 큐가 있으면 True, 없으면(종료/미존재) False.

    큐로 전달하므로 대화형 HITL 은 여러 턴(입력 여러 번 + 완료 1번)을 모두 받을 수 있다.
    """
    q = _hitl_queues.get(decision_id)
    if q is not None:
        q.put_nowait(payload)
        return True
    return False


async def wait_hitl(
    events: asyncio.Queue,
    *,
    kind: str,
    title: str,
    prompt: str,
    options: list[dict] | None = None,
    extra: dict | None = None,
    timeout_s: int | None = None,
    owner: str | None = None,
    run_id: str | None = None,
) -> dict:
    """hitl 이벤트를 방출하고 사용자 응답을 기다린다(최대 timeout_s).

    소유권(`owner`)·런바인딩(`run_id`)은 큐 생성 시점에 등록해 레이스 창을 없앤다(falsy 면
    미등록 — session 펌프 폴백). 타임아웃 시 asyncio.TimeoutError 를 던진다(호출 노드가 실패
    이벤트로 변환). timeout_s 미지정 시 config.hitl_timeout_s(단일 소스)를 쓴다.

    대기(q.get) 동안 런 활동 시간 예산은 일시정지된다(HITL 대기 제외 — `_BudgetPausedQueue`).
    """
    if timeout_s is None:
        timeout_s = get_settings().hitl_timeout_s
    decision_id = uuid.uuid4().hex
    q: asyncio.Queue = _BudgetPausedQueue(run_id)
    _hitl_queues[decision_id] = q
    if owner:
        _hitl_owner[decision_id] = owner
    if run_id:
        _hitl_run_id[decision_id] = run_id
    frame: dict = {"id": decision_id, "kind": kind, "title": title, "prompt": prompt}
    if options:
        frame["options"] = options
    if extra:
        frame.update(extra)
    await events.put({"hitl": frame})
    try:
        return await asyncio.wait_for(q.get(), timeout=timeout_s)
    finally:
        _hitl_queues.pop(decision_id, None)
        _hitl_owner.pop(decision_id, None)
        _hitl_run_id.pop(decision_id, None)
