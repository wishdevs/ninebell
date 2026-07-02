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

# decision_id → 대기 큐. 노드가 만들고, resolve_hitl 이 넣고, 노드가 pop 한다.
_hitl_queues: dict[str, asyncio.Queue] = {}
# decision_id → owner(세션 사용자 식별자). 값이 있으면 그 사용자만 resolve 가능.
_hitl_owner: dict[str, str] = {}


def open_hitl_channel(decision_id: str) -> asyncio.Queue:
    """지속(멀티턴) HITL 큐 등록 — 대화형 노드용.

    `wait_hitl`(단발)과 달리 노드 수명 동안 같은 decision_id 로 큐를 유지해, 도구 실행 등
    턴 사이 공백에도 사용자 메시지가 유실되지 않고 큐잉된다. 반드시 `close_hitl_channel` 로 정리.
    소유권(`_hitl_owner`)은 LiveSession 이 hitl 프레임을 볼 때 자동 등록한다.
    """
    q: asyncio.Queue = asyncio.Queue()
    _hitl_queues[decision_id] = q
    return q


def close_hitl_channel(decision_id: str) -> None:
    """`open_hitl_channel` 로 연 채널 정리(큐·소유권 제거)."""
    _hitl_queues.pop(decision_id, None)
    _hitl_owner.pop(decision_id, None)


def set_hitl_owner(decision_id: str, owner: str | None) -> None:
    """이 개입의 소유자를 등록(옵션 A 격리). owner 가 falsy 면 개방(스크립트 경로)."""
    if owner:
        _hitl_owner[decision_id] = owner


def hitl_owner(decision_id: str) -> str | None:
    return _hitl_owner.get(decision_id)


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
) -> dict:
    """hitl 이벤트를 방출하고 사용자 응답을 기다린다(최대 timeout_s).

    소유권은 LiveSession 이 hitl 이벤트를 보며 등록하므로 여기서는 큐만 만든다.
    타임아웃 시 asyncio.TimeoutError 를 던진다(호출 노드가 실패 이벤트로 변환).
    timeout_s 미지정 시 config.hitl_timeout_s(단일 소스)를 쓴다.
    """
    if timeout_s is None:
        timeout_s = get_settings().hitl_timeout_s
    decision_id = uuid.uuid4().hex
    q: asyncio.Queue = asyncio.Queue()
    _hitl_queues[decision_id] = q
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
