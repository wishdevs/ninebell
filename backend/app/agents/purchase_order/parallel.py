"""구매발주 병렬 워커 공용부 — 세션 부트스트랩 + FE 워커 칩 브로드캐스트.

같은 계정 동시 3세션 허용은 `e2e/concurrent_session_probe.py` 실측(2026-09-01 — 강제
로그아웃·세션 간섭 없음). 부트스트랩 로그인은 **순차**(동시 로그인 발사는 미실측).
self_approve 가 풀을 만들고 state["worker_pool"] 로 place_orders 에 넘겨 재사용한다
(로그인 1회) — 정리는 마지막 사용자(place_orders)가, 그 전에 런이 죽으면 러너의
browser.close 가 컨텍스트까지 정리한다.
"""

from __future__ import annotations

import asyncio

from app.live.events import emit_workers
from nbkit.browser.popups import install_notice_autoclose
from nbkit.patterns.login_flow import ensure_logged_in
from nbkit.patterns.user_type_flow import ensure_user_type

WORKERS = 3  # 동시 브라우저 세션 상한 — concurrent_session_probe 실측 범위(3) 이내


async def bootstrap_worker_page(browser, *, userid: str, password: str, base: str, scale) -> tuple:
    """추가 워커용 새 브라우저 컨텍스트+페이지 — 로그인→SCM 유저타입까지. 반환 (ctx, page).

    실패는 예외로 승격(호출부가 해당 워커만 제외하고 진행). 메뉴 진입은 각 노드의 워커 루프
    책임이다(화면이 노드마다 다르다).
    """
    from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # 지연 import — 순환 방지

    ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
    install_notice_autoclose(ctx)
    page = await ctx.new_page()
    if scale and scale != 1.0:
        page = _ScaledPage(page, scale)
    await ensure_logged_in(page, userid, password, base)
    await ensure_user_type(page, "SCM")
    return ctx, page


class WorkerTracker:
    """워커 상태 프레임 브로드캐스터 — FE 라이브 스테이지 칩({"workers": [...]}) 계약.

    병렬(n>1)일 때만 방출한다 — 단독 직렬 런은 기존 로그로 충분(재생 노이즈 방지).
    """

    def __init__(self, events: asyncio.Queue, n: int):
        self.events = events
        self.state: dict[int, dict] = {i: {"id": i + 1, "status": "idle"} for i in range(n)}
        self.broadcast = n > 1

    async def emit(self) -> None:
        if self.broadcast:
            await emit_workers(self.events, [dict(self.state[k]) for k in sorted(self.state)])

    async def working(self, wid: int, prq: str, seq=None) -> None:
        self.state[wid] = {"id": wid + 1, "prq": prq, "seq": seq, "status": "working"}
        await self.emit()

    async def done(self, wid: int) -> None:
        self.state[wid] = {"id": wid + 1, "status": "done"}
        await self.emit()
