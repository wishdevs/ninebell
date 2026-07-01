"""로그인 플로우 — ensure_logged_in(page, …): 로그인 + 프로필 추출 + 진행 이벤트.

엔진의 첫 노드가 쓰는 템플릿. 실패 시 :class:`AuthError` 를 올린다(engine 이 error 이벤트로).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from nbkit.omnisol.auth import omnisol_login
from nbkit.omnisol.profile import read_profile
from nbkit.patterns import EmitFn, emit_shot, emit_step


async def ensure_logged_in(
    page: Any,
    userid: str,
    password: str,
    base: str,
    *,
    read_profile_after: bool = True,
    emit: Optional[EmitFn] = None,
) -> dict:
    """page 에 로그인하고 (옵션) 프로필을 읽어 반환.

    반환: ``{"profile": {...}|None}``. 진행 단계(login running/done/failed)와 스냅샷을 emit.
    """
    await emit_step(emit, "login", "running")
    t0 = time.monotonic()
    try:
        await omnisol_login(page, userid, password, base)
    except Exception:
        await emit_step(emit, "login", "failed")
        raise
    profile = await read_profile(page) if read_profile_after else None
    await emit_shot(emit, page)
    await emit_step(emit, "login", "done", int((time.monotonic() - t0) * 1000))
    return {"profile": profile}
