"""사용자유형 플로우 — ensure_user_type(page, target): 실클릭 전환 + 진행 이벤트.

에이전트마다 필요한 유형이 다르다(BOM 수집=인사, 결의서입력=회계). 전환은 실클릭으로만
(auth.switch_user_type). 실패 시 :class:`UserTypeError`.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from nbkit.omnisol.auth import switch_user_type
from nbkit.patterns import EmitFn, emit_shot, emit_step


async def ensure_user_type(
    page: Any, target: str, *, emit: Optional[EmitFn] = None
) -> None:
    """사용자유형을 ``target``('인사'|'회계')으로 보장(이미 맞으면 전환 생략)."""
    await emit_step(emit, "user_type", "running")
    t0 = time.monotonic()
    try:
        await switch_user_type(page, target)
    except Exception:
        await emit_step(emit, "user_type", "failed")
        raise
    await emit_shot(emit, page)
    await emit_step(emit, "user_type", "done", int((time.monotonic() - t0) * 1000))
