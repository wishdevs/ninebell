"""저장 확정 구간 취소 보호 — asyncio.shield 공용 헬퍼.

왜 필요한가: 런 취소 경로가 4개다(사용자 취소, 클라 끊김 리퍼, 배포 셧다운, 런 시간 예산
워치독 — 전부 그래프 태스크 cancel). CancelledError 가 F7 저장 확정 구간(F7 클릭→확인
모달→저장 판정) 한가운데 주입되면 ERP 엔 저장됐는데 기록은 취소/실패인 **반저장**이 남고,
회계 데이터라 사건당 수작업 대사가 필요하다. `app/agents/ACTIONS.md` 부작용 등급
'확정'(`[저장]` F7) 구간을 이 헬퍼로 보호한다.

핵심 견고성: 외부 취소는 한 번이 아니다 — 워치독이 graph_task.cancel() 한 뒤 러너 finally 가
task.cancel() 을 **한 번 더** 호출하는 실경로가 있다(runner.py). CancelledError 를 한 번만
잡으면 두 번째 주입에 뚫리므로, 내부 완료까지 **루프로 반복 흡수**한다.

cap_s 근거: save_document 의 F7 후 관찰 상한이 실시간 16s(steps._SAVE_CAP_S)이고 확인 모달
클릭·판정에 수 초가 더 든다 — 기본 30s 는 정상 확정 구간을 넉넉히 덮되, 행이 걸린 채
셧다운을 무한정 막지는 않는 값이다.

한계: asyncio.shield 는 같은 이벤트 루프 안의 태스크 취소만 억류한다 — 이벤트 루프 자체
종료나 프로세스 강제 종료(SIGKILL·컨테이너 stop-timeout 초과)까지는 못 막는다. 셧다운
드레인(session.close → pump → runner finally 의 `await task` 가 그래프 태스크 완료를
대기)이 짝으로 있어야 이 보호가 성립한다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from app.live.events import emit_log

logger = logging.getLogger("app.agents.common.commit_shield")

# cap 초과로 내부 task 를 취소한 뒤 정리(finally)가 끝나길 기다리는 짧은 유예(초).
_DRAIN_S = 3.0


def _outcome(inner: asyncio.Task, label: str) -> tuple[str, str]:
    """완료된 내부 task 의 결과 → (런 로그 문구, 레벨) — 취소 억류 후 로그 확정용.

    저장 함수(save_document 계열)는 거부를 예외가 아니라 {"ok": False, reason} 으로
    반환하므로, dict 결과의 ok 를 봐야 '저장됨/안 됨'을 바르게 적을 수 있다.
    """
    if inner.cancelled():
        return (f"⚠ {label} 내부 작업이 취소로 종료 — 확정 여부 불명, ERP 상태 확인 필요", "error")
    exc = inner.exception()
    if exc is not None:
        return (f"{label} 실패 후 중단(저장 안 됨 추정) — {exc}", "warn")
    result = inner.result()
    if isinstance(result, dict) and result.get("ok") is False:
        reason = result.get("reason") or str(result)
        return (f"{label} 거부 후 중단(저장 안 됨) — {reason}", "warn")
    return (f"{label} 완료 후 중단(저장됨)", "warn")


async def _notify(events: asyncio.Queue, message: str, level: str) -> None:
    """억류 중 런 로그 방출 — 방출 실패(재취소 주입 포함)가 보호 루프를 깨선 안 된다."""
    try:
        await emit_log(events, message, level)
    except BaseException:  # noqa: BLE001 — CancelledError 포함 전부 흡수(로그는 best-effort).
        logger.debug("commit_shield: 억류 로그 방출 실패(무시)", exc_info=True)


async def _wait_absorbing(inner: asyncio.Task, deadline: float, label: str) -> int:
    """deadline 까지 inner 완료를 대기 — 반복 주입되는 CancelledError 를 흡수(횟수 반환).

    asyncio.wait 는 외부 취소·타임아웃 어느 쪽에도 inner 를 취소하지 않는다(shield 재래핑
    불필요) — 재주입 CancelledError 는 wait 의 await 에서 터져 여기서 흡수된다.
    """
    absorbed = 0
    while not inner.done():
        remain = deadline - time.monotonic()
        if remain <= 0:
            break
        try:
            await asyncio.wait({inner}, timeout=remain)
        except asyncio.CancelledError:
            absorbed += 1
            logger.info("commit_shield: 취소 재주입 흡수 — %s (추가 %d회)", label, absorbed)
    return absorbed


async def shielded_commit(
    factory_or_coro: Callable[[], Awaitable[Any]] | Awaitable[Any],
    *,
    events: asyncio.Queue,
    label: str,
    cap_s: float = 30.0,
) -> Any:
    """확정(저장) 코루틴을 asyncio.shield 로 감싸 외부 취소로부터 완료까지 보호한다.

    취소가 없으면 결과 그대로 반환·예외 그대로 전파(완전 투명 — 정상 경로 오버헤드 0).
    외부 취소가 오면: ① "확정 중 — 완료 후 중단됩니다" 안내 1회 ② 내부 task 를 실시간 상한
    cap_s 까지 계속 대기(반복 주입 CancelledError 루프 흡수) ③ 내부 완료 시 결과를 로그로
    확정한 뒤 CancelledError 재발생(정상 취소 흐름 복귀) ④ cap_s 초과 시 내부 취소 후
    "확정 미완 — ERP 상태 확인 필요" 경고와 함께 재발생.

    factory_or_coro: 코루틴 또는 0-인자 팩토리(늦은 바인딩 — 모듈 속성 monkeypatch 호환).
    """
    coro = factory_or_coro() if callable(factory_or_coro) else factory_or_coro
    inner: asyncio.Task = asyncio.ensure_future(coro)
    try:
        return await asyncio.shield(inner)
    except asyncio.CancelledError:
        if inner.cancelled():
            raise  # 내부 자체가 취소된 것(외부 억류 대상 아님) — 그대로 전파.
    # ── 외부 취소 억류 구간 — 내부 완료(또는 cap)까지 취소를 붙잡는다 ─────────────
    logger.warning("commit_shield: 외부 취소 억류 시작 — %s (cap %.0fs)", label, cap_s)
    await _notify(events, f"⏳ {label} 확정 중 — 완료 후 중단됩니다", "warn")
    absorbed = 1 + await _wait_absorbing(inner, time.monotonic() + cap_s, label)
    if inner.done():
        message, level = _outcome(inner, label)
    else:
        # cap 초과 — 내부를 취소하고 짧게 정리를 기다린 뒤 정상 취소 흐름으로 복귀.
        inner.cancel()
        absorbed += await _wait_absorbing(inner, time.monotonic() + _DRAIN_S, label)
        if inner.done() and not inner.cancelled() and inner.exception() is None:
            # 취소 직전 정상 완료(경합) — 결과 기준으로 확정 로그.
            message, level = _outcome(inner, label)
        else:
            if inner.done():
                inner.cancelled() or inner.exception()  # 예외 회수(미회수 경고 방지).
            message = f"⚠ {label} 확정 미완(상한 {cap_s:.0f}s 초과) — ERP 상태 확인 필요"
            level = "error"
    logger.warning("commit_shield: %s (취소 흡수 %d회)", message, absorbed)
    await _notify(events, message, level)
    raise asyncio.CancelledError()
