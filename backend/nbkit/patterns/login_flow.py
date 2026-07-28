"""로그인 플로우 — ensure_logged_in(page, …): 로그인 + 프로필 추출 + 진행 이벤트.

엔진의 첫 노드가 쓰는 템플릿. 실패 시 :class:`AuthError` 를 올린다(engine 이 error 이벤트로).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from nbkit.browser.popups import PopupWatcher
from nbkit.omnisol.auth import omnisol_login
from nbkit.omnisol.modals import dismiss_notice_popup
from nbkit.omnisol.profile import read_profile
from nbkit.patterns import EmitFn, emit_log, emit_shot, emit_step


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
    # 로그인 **전에** 팝업 감시를 건다 — 계정에 따라 로그인 도중/직후 회사 홈페이지가 **별도
    # 브라우저 창**으로 뜬다(실측 2026-07-27: 계정 '석대현' → www.ninebell.co.kr, 메인 페이지의
    # 인페이지 다이얼로그는 0개라 공지 팝업 닫기로는 절대 안 잡힌다). 감시는 이 함수 안에서만
    # 유지하고 반드시 뗀다 — 결제(결재)창도 다른 호스트의 시스템 팝업이라 상시 자동 닫기는 금물.
    context = getattr(page, "context", None)
    # auto_close_base: 감시 구간 동안 **도착하는 즉시** 외부 호스트 창을 닫는다(실측 2026-07-27:
    # 이 팝업은 로그인 시퀀스 중 시점이 일정하지 않아 한 지점 sweep 만으론 놓친다).
    watcher = PopupWatcher(context, page, auto_close_base=base).start() if context is not None else None
    try:
        try:
            await omnisol_login(page, userid, password, base)
        except Exception:
            await emit_step(emit, "login", "failed")
            raise
        # 로그인 직후 뜨는 '공지' 레이어 팝업(전 화면 차단)을 먼저 닫는다 — 이후 어떤 조작(아바타
        # 클릭·프로필 읽기·메뉴 진입)보다 반드시 먼저. 전 에이전트 공통(2026-07-21). 없으면 no-op.
        # 관찰창 4s: 팝업은 로그인 ~1.5s 뒤 비동기 렌더 — 느린 세션이 2s 를 넘겨 통째로 놓치면
        # '메뉴 이동 후에야 JIT 방어가 닫는' 이중 처리가 된다(2026-07-23 사용자 관찰). 팝업이
        # 있으면 조기 반환이라 추가 비용은 공지 없는 날에만 발생한다.
        await dismiss_notice_popup(page, appear_cap_ms=4_000)
        # 시스템 팝업(별도 창) 정리 — 공지 관찰창(위) 동안 이미 떴으면 대기 없이 즉시 닫는다.
        # ERP 와 **호스트가 다른** 창만 닫는다(업무 창 보호). 프로필 읽기·메뉴 진입 전에 치워야
        # 포커스가 뺏긴 채 다음 조작이 진행되지 않는다.
        closed: list[str] = []
        if watcher is not None:
            # ⚠ 대기 0ms: 실제 닫기는 **도착 즉시**(auto_close) 일어나므로 여기서 기다릴 이유가
            #   없다. 관찰 대기를 두면 팝업이 없는 계정·에이전트 전부가 그 시간을 물어 로그인이
            #   느려진다(실측 2026-07-27: 2s 관찰 = 전 에이전트 로그인 +2s). 이 호출은 지금까지
            #   닫힌 것을 회수해 보고하는 용도다.
            closed += await watcher.close_foreign(base, appear_cap_ms=0)
        profile = await read_profile(page) if read_profile_after else None
        # 프로필 읽기(아바타 클릭 등) 중에 뜬 창까지 마지막으로 훑는다 — 대기 없이 0ms 확인.
        if watcher is not None:
            closed += await watcher.close_foreign(base, appear_cap_ms=0)
        for url in closed:
            await emit_log(emit, f"로그인 시 뜬 외부 창을 닫았습니다 — {url}", "info")
    finally:
        if watcher is not None:
            watcher.stop()  # 이후 정상 업무 팝업(결제창 등)은 절대 건드리지 않는다.
    await emit_shot(emit, page)
    await emit_step(emit, "login", "done", int((time.monotonic() - t0) * 1000))
    return {"profile": profile}
