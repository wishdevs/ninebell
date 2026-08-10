"""nbkit.patterns — 프리미티브를 조합한 재사용 플로우 템플릿.

login_flow(ensure_logged_in) · user_type_flow(ensure_user_type) ·
menu_navigate_flow(navigate) · grid_read_flow(read_grid_with_fallback).

각 플로우는 선택적 ``emit`` 콜백으로 진행 이벤트({step}/{log}/{screenshot})를 흘려보낸다.
엔진(P2/P3)의 이벤트 큐에 **직접 의존하지 않도록** 느슨한 콜백 하나만 받는다 — 큐가 없으면
no-op. 실패는 도메인 예외(AuthError/MenuError/GridError…)로 올려 엔진이 분기하게 한다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from nbkit.browser.debug import screenshot_data_url

# 이벤트 방출 콜백: dict 이벤트 하나를 받는 async 함수. None 이면 no-op.
EmitFn = Callable[[dict], Awaitable[None]]


async def noop_emit(event: dict) -> None:  # noqa: ARG001 — 의도적 no-op
    return None


def resolve_emit(emit: Optional[EmitFn]) -> EmitFn:
    return emit or noop_emit


async def emit_step(
    emit: Optional[EmitFn], step: str, status: str, ms: Optional[int] = None
) -> None:
    """진행 단계 이벤트 ``{step, status, ms?}``."""
    ev: dict = {"step": step, "status": status}
    if ms is not None:
        ev["ms"] = ms
    await resolve_emit(emit)(ev)


async def emit_log(emit: Optional[EmitFn], message: str, level: str = "info") -> None:
    """런 로그 이벤트 ``{log, level}``."""
    await resolve_emit(emit)({"log": message, "level": level})


async def emit_shot(emit: Optional[EmitFn], page: Any, window: str = "parent") -> None:
    """현재 화면 스냅샷 이벤트 ``{screenshot: dataURL}``(실패 시 생략).

    window: 어느 브라우저 창의 스냅샷인지('parent' 기본 / 'child'=팝업·자식 창). 기본 'parent'
    이면 window 키를 넣지 않아 기존 ~30개 호출부와 프레임이 바이트 동일하다(하위 호환).
    """
    if emit is None:
        return
    data_url = await screenshot_data_url(page)
    if data_url:
        frame: dict = {"screenshot": data_url}
        if window != "parent":
            frame["window"] = window
        await emit(frame)
