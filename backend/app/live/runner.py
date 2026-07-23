"""워크플로우 러너 — 워크플로우 무관 실행 오케스트레이션.

fresh 헤드리스 브라우저를 띄우고(세마포어로 동시 실행 제한), 페이지·events 큐·자격증명·
파라미터를 그래프 state 에 주입한 뒤 그래프를 실행하며 노드가 방출한 이벤트를 스트리밍한다.
스크린캐스트 펌프를 병행해 라이브 화면 프레임도 흘린다. 종료/클라 끊김 시 러너·캐스트를
취소하고 브라우저를 finally 에서 닫아 메모리를 즉시 반환한다.

ninebell-bak `erp/graph.py` 의 `run_graph` 를 워크플로우 무관 러너로 이식했다. 원본은 login
노드가 페이지를 만들었지만, 여기선 러너가 페이지를 만들어 state["page"] 로 주입한다(계약).

그래프 계약: 컴파일된 LangGraph(또는 `.ainvoke(state)` 를 가진 객체). state 는
`{"page", "browser", "events", "userid", "password", "params"}`. 노드는 `events`(asyncio.Queue)
로 `app.live.events` 헬퍼를 통해 진행 이벤트를 방출하고, 최종은 result/error/transactions 로.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import traceback
from typing import Any, AsyncIterator, Awaitable, Callable

from .screencast import screencast_pump

logger = logging.getLogger(__name__)


# ── 대기 배율(속도 튜닝·극단 테스트) ─────────────────────────────────────────────
# CARD_DELAY_SCALE 로 모든 page.wait_for_timeout(고정 settle·폴 간격·닫힘 대기)을 한 번에
# 스케일한다(코드 40여 곳 무수정). 예: 0.2=1/5 로 극단 축소 → 어디서 깨지는지 파악.
# 1.0(기본)이면 프록시 없이 원본 page 그대로.
class _ScaledPage:
    """page 위임 프록시 — wait_for_timeout 만 배율 적용, 나머지 속성/메서드는 원본 위임."""

    def __init__(self, page: Any, scale: float):
        object.__setattr__(self, "_page", page)
        object.__setattr__(self, "_scale", scale)

    async def wait_for_timeout(self, ms: float) -> Any:
        return await self._page.wait_for_timeout(max(0.0, ms * self._scale))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._page, name)


def _resolve_scale(default_scale: float | None) -> float:
    """대기 배율 결정 — env CARD_DELAY_SCALE 가 있으면 그것(테스트 override) 우선, 없으면
    호출부가 준 per-run 기본값(card-collect=0.15 등), 둘 다 없으면 1.0(무변경)."""
    env = os.environ.get("CARD_DELAY_SCALE")
    if env:
        try:
            return float(env)
        except ValueError:
            return 1.0
    return default_scale if default_scale else 1.0


def _maybe_scale_page(page: Any, default_scale: float | None = None) -> Any:
    if page is None:
        return None
    scale = _resolve_scale(default_scale)
    if scale == 1.0 or scale <= 0:
        return page
    logger.info("run_workflow: 대기 배율 scale=%s 적용", scale)
    return _ScaledPage(page, scale)

# 브라우저 팩토리: fresh 헤드리스 브라우저를 반환하는 async 콜러블(playwright chromium 등).
BrowserFactory = Callable[[], Awaitable[Any]]

# 라이브 워크플로우 페이지 뷰포트. Playwright 기본값(1280×720)은 옴니솔 그리드형 UI에 좁아
# 셀렉터가 화면 밖으로 밀릴 수 있어, 탐색 단계에서 검증된 크기(1440×900)로 고정한다.
LIVE_VIEWPORT: dict[str, int] = {"width": 1440, "height": 900}

# 자식 팝업(전자결재 결제창) 전용 뷰포트 — 결제 전표는 세로로 긴 문서라 부모(900) 높이로는
# 아래가 잘린다. 세로를 키워 한 프레임에 더 많은 폼이 렌더·캡처되게 한다(FE 는 고정 카드에
# object-contain 으로 얹어 카드 너비와 무관하게 전체를 보여준다).
CHILD_VIEWPORT: dict[str, int] = {"width": 1440, "height": 1120}

# ── 세션 워밍(storage_state 캐시) — Phase 2b 속도 최적화 ─────────────────────────
# 인증 쿠키(세션 스코프)를 userid 별로 **RAM 에만** 보관한다(디스크 저장 금지 — 세션 토큰).
# 프로브 실측(2026-07-04): 같은 상태로 컨텍스트 3개 동시 사용해도 ERP 킥 없음, 웜 진입 ~4s
# (콜드 로그인+유형전환+메뉴 ≈ 13-20s 대체). 만료/무효 상태여도 login 노드가 로그인 폼을
# 보면 정상 로그인하므로(자가 치유) 이 캐시는 **순수 최적화**이며 정합성에 영향 없다.
_STATE_TTL_S = 1800.0  # 30분 — ERP 서버 세션 만료 전 재사용 확률을 높이는 보수적 TTL.
# (site, userid) → (saved_at monotonic, storage_state). site 로 스코프해 타 사이트 워크플로우와
# 쿠키가 섞이지 않는다(스케일링: 옴니솔 외 사이트 에이전트 대비).
_state_cache: dict[tuple[str, str], tuple[float, dict]] = {}
# 웜 판정용 로그인 폼 셀렉터 기본값(옴니솔 nbkit.omnisol.selectors.LOGIN_USERID 와 동일 값) —
# 러너는 워크플로우 무관 계층이라 문자열로만 참조한다. WorkflowSpec.login_form_selector 로
# 사이트별 재정의(None=캐시 비활성). 폼이 없으면 인증된 세션으로 보고 상태를 캐시한다.
_LOGIN_FORM_SELECTOR = "#userid"


def _cached_state(site: str, userid: str | None) -> dict | None:
    """TTL 내 storage_state 반환(만료 시 제거·None)."""
    if not userid:
        return None
    key = (site, userid)
    hit = _state_cache.get(key)
    if hit is None:
        return None
    saved_at, state = hit
    if time.monotonic() - saved_at > _STATE_TTL_S:
        _state_cache.pop(key, None)
        return None
    return state


async def _save_state(
    page: Any, site: str, userid: str | None, login_form_selector: str | None
) -> None:
    """런 종료 시 인증돼 있으면 storage_state 를 캐시(다음 런 웜 진입). 실패는 조용히 무시."""
    if page is None or not userid or not login_form_selector:
        return
    try:
        authed = await page.evaluate(
            "(sel) => !document.querySelector(sel)", login_form_selector
        )
        if authed:
            _state_cache[(site, userid)] = (
                time.monotonic(),
                await page.context.storage_state(),
            )
    except Exception:  # noqa: BLE001 — 캐시 갱신 실패가 런 결과를 바꿔선 안 된다.
        logger.debug("storage_state 캐시 갱신 실패(무시)", exc_info=True)


async def run_workflow(
    graph: Any,
    browser_factory: BrowserFactory | None,
    creds: dict | None,
    params: dict | None,
    *,
    semaphore: asyncio.Semaphore | None = None,
    screencast: bool = True,
    owner: str | None = None,
    run_id: str | None = None,
    delay_scale: float | None = None,
    site: str = "omnisol",
    login_form_selector: str | None = _LOGIN_FORM_SELECTOR,
) -> AsyncIterator[dict]:
    """그래프를 실행하며 노드 진행 이벤트를 스트리밍한다.

    yield: `app.live.events` 계약의 프레임들(step/log/screenshot/hitl/chat/transactions),
           그리고 최종 result/error. 그래프가 state 에 result/error 만 남기고 이벤트를 안
           내면 여기서 최종 프레임을 방출한다(노드가 이미 냈으면 중복 없이 종료).

    browser_factory=None(WorkflowSpec.needs_browser=False) 이면 브라우저·스크린캐스트·세션캐시
    경로를 전부 생략한다 — 순수 API/LLM 워크플로우용. state 의 page/browser 는 None.
    """
    creds = creds or {}
    events: asyncio.Queue = asyncio.Queue()
    limiter = semaphore or contextlib.nullcontext()
    async with limiter:
        browser = await browser_factory() if browser_factory is not None else None
        page = None
        # 세션 워밍: 캐시된 storage_state 가 있으면 인증 쿠키를 실은 컨텍스트로 시작 —
        # login 노드가 로그인 폼 없이 통과(웜 진입). 실패는 콜드 경로로 폴백.
        warm = _cached_state(site, creds.get("userid")) if browser is not None else None
        if warm is not None:
            try:
                ctx = await browser.new_context(storage_state=warm, viewport=LIVE_VIEWPORT)
                page = await ctx.new_page()
                logger.info("run_workflow: 세션 워밍 컨텍스트 사용(userid=%s)", creds.get("userid"))
            except Exception:
                logger.warning("세션 워밍 컨텍스트 실패 — 콜드 경로 폴백", exc_info=True)
                page = None
        if page is None and browser is not None:
            try:
                page = await browser.new_page(viewport=LIVE_VIEWPORT)
            except Exception:
                logger.warning("run_workflow: new_page 실패 — 페이지 없이 진행")
                page = None

        raw_page = page  # storage_state 저장은 원본 page.context 로(프록시 우회).
        # 대기 배율 프록시. env(CARD_DELAY_SCALE) 우선, 없으면 per-run delay_scale(card-collect=0.15).
        page = _maybe_scale_page(page, delay_scale)

        state: dict = {
            "page": page,
            "browser": browser,
            "events": events,
            "userid": creds.get("userid"),
            "password": creds.get("password"),
            "params": params or {},
            # HITL 소유권/런바인딩을 노드가 채널 오픈 시점에 등록하도록 주입(레이스 창 제거).
            # owner=세션 사용자 id(str(user.id) — /runs/hitl 검증값과 동일), run_id=세션/런 id.
            "owner": owner,
            "run_id": run_id,
        }

        async def runner() -> None:
            try:
                final = await graph.ainvoke(state)
                await events.put({"_final": final or {}})
            except Exception:
                # run_id 를 함께 남겨 서버 로그 ↔ AgentRun 상관 조회가 가능하게 한다.
                logger.exception("workflow run failed run_id=%s", run_id)
                # 예외 스택 꼬리를 런 로그(error)로도 방출 — 서버 로그 없이도 실패 원인을
                # 몇 주 뒤 재구성할 수 있게 한다. 최종 error 프레임 계약은 불변(log 프레임 추가만).
                tail = "\n".join(traceback.format_exc().splitlines()[-15:])
                await events.put({"log": f"예외 스택(마지막 15줄):\n{tail}", "level": "error"})
                await events.put({"_final": {"error": "실행 중 오류(워크플로우/브라우저)."}})

        task = asyncio.create_task(runner())
        cast: asyncio.Task | None = None
        # 자식 창(팝업) 스크린캐스트 태스크들 — 진짜 두 번째 Playwright Page(예: SSO 교차출처
        # 전자결재 창)가 열리면 창별로 하나씩 생기고, 종료 시 부모 cast 와 함께 취소한다.
        child_casts: list[asyncio.Task] = []
        # context.on("page") 를 등록한 컨텍스트(teardown 에서 리스너 제거용). None = 미등록.
        page_listener_ctx: Any | None = None
        if screencast and page is not None:
            cast = asyncio.create_task(screencast_pump(page, events))

            async def _cast_child(pg: Any) -> None:
                # 자식 팝업(전자결재 결제창 등)은 window.open 고정 크기라 부모 컨텍스트 뷰포트를
                # 못 물려받는다 → 결제 폼이 창보다 넓으면 캐스트가 뜨기도 전에 오른쪽이 잘린다.
                # 부모와 같은 크기로 강제 리사이즈해 폼 전체가 렌더·캡처되게 한다(FE 는 실제 비율로 표시).
                try:
                    await pg.set_viewport_size(CHILD_VIEWPORT)
                except Exception:
                    logger.debug("자식 페이지 뷰포트 강제 실패(무시)", exc_info=True)
                await screencast_pump(pg, events, window="child")

            def _on_new_page(new_page: Any) -> None:
                # context 에 새 Page 가 생기면(팝업/window.open) 자식 스크린캐스트를 시작하고,
                # 그 페이지가 닫히면 펌프를 취소한 뒤 closed 전이 프레임을 방출한다(FE=부모창 복귀).
                child_cast = asyncio.create_task(_cast_child(new_page))
                child_casts.append(child_cast)

                def _on_child_close(_evt: Any = None) -> None:
                    child_cast.cancel()
                    try:
                        events.put_nowait({"window": "child", "closed": True})
                    except Exception:
                        pass

                try:
                    new_page.on("close", _on_child_close)
                except Exception:
                    logger.debug("자식 페이지 close 핸들러 등록 실패(무시)", exc_info=True)

            # raw_page(프록시 우회)의 실제 context 에 등록 — 초기 페이지는 이미 생성돼 이 핸들러
            # 이전이라 트리거되지 않고, 이후 열리는 팝업만 잡는다.
            if raw_page is not None:
                try:
                    raw_page.context.on("page", _on_new_page)
                    page_listener_ctx = raw_page.context
                except Exception:
                    logger.debug("context.on('page') 등록 실패(무시)", exc_info=True)
        try:
            while True:
                ev = await events.get()
                if "_final" in ev:
                    final = ev["_final"] or {}
                    if final.get("error"):
                        yield {"error": final["error"]}
                    elif "result" in final:
                        yield {"result": final["result"]}
                    # else: 노드가 이미 result/transactions 를 방출함 → 조용히 종료.
                    break
                yield ev
        finally:
            # 클라 끊김/종료 시 러너·캐스트를 즉시 취소하고 브라우저를 닫아 메모리를 반환한다.
            # 새 팝업 리스너를 먼저 제거해, teardown 중(browser.close 전) 열리는 팝업이 또 다른
            # 자식 펌프를 만들지 않게 한다(늦은 펌프 유출 방지).
            if page_listener_ctx is not None:
                try:
                    page_listener_ctx.remove_listener("page", _on_new_page)
                except Exception:
                    logger.debug("context.remove_listener('page') 실패(무시)", exc_info=True)
            if cast is not None:
                cast.cancel()
            for child_cast in child_casts:
                child_cast.cancel()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("runner task 종료 예외 무시", exc_info=True)
            # 브라우저 닫기 전에 인증 세션 상태를 캐시(다음 런 웜 진입). 실패는 무시.
            await _save_state(raw_page, site, creds.get("userid"), login_form_selector)
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    logger.debug("browser.close 예외 무시", exc_info=True)
            # browser.close 전후로 열렸을 수 있는 자식 펌프까지 확실히 취소 — 초기 스냅샷 이후
            # 추가된 late 펌프(teardown 중 팝업)를 fresh 스냅샷으로 다시 취소한다.
            for child_cast in list(child_casts):
                child_cast.cancel()
