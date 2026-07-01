"""메뉴 진입 플로우 — navigate(page, …): 딥링크 진입 + 진행 이벤트.

navigator.navigate_menu 를 감싸 step/log/스냅샷을 emit. 실패 시 :class:`MenuError`.
:class:`MenuSchema` 로 진입하는 :func:`navigate_schema` 도 제공(딥링크·라벨·기대그리드 자동).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from nbkit.omnisol.menu_schemas import MenuSchema
from nbkit.omnisol.navigator import navigate_menu
from nbkit.patterns import EmitFn, emit_log, emit_shot, emit_step


async def navigate(
    page: Any,
    menu_path: str,
    base: str,
    *,
    label: str = "메뉴",
    grids_required: int = 1,
    emit: Optional[EmitFn] = None,
) -> None:
    """``base+menu_path`` 딥링크로 진입(그리드 로드 폴링·권한팝업 즉시실패)."""
    await emit_step(emit, "menu_nav", "running")
    await emit_log(emit, f"{label} 메뉴 진입 중…", "info")
    t0 = time.monotonic()
    try:
        await navigate_menu(page, menu_path, base, label=label, grids_required=grids_required)
    except Exception:
        await emit_step(emit, "menu_nav", "failed")
        raise
    await emit_shot(emit, page)
    await emit_step(emit, "menu_nav", "done", int((time.monotonic() - t0) * 1000))


async def navigate_schema(
    page: Any, schema: MenuSchema, base: str, *, emit: Optional[EmitFn] = None
) -> None:
    """:class:`MenuSchema` 로 진입(딥링크·라벨·기대 그리드 수를 스키마에서)."""
    await navigate(
        page,
        schema.deeplink,
        base,
        label=schema.label,
        grids_required=schema.grids_expected,
        emit=emit,
    )
