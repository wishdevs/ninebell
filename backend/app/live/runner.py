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
from typing import Any, AsyncIterator, Awaitable, Callable

from .screencast import screencast_pump

logger = logging.getLogger(__name__)

# 브라우저 팩토리: fresh 헤드리스 브라우저를 반환하는 async 콜러블(playwright chromium 등).
BrowserFactory = Callable[[], Awaitable[Any]]


async def run_workflow(
    graph: Any,
    browser_factory: BrowserFactory,
    creds: dict | None,
    params: dict | None,
    *,
    semaphore: asyncio.Semaphore | None = None,
    screencast: bool = True,
) -> AsyncIterator[dict]:
    """그래프를 실행하며 노드 진행 이벤트를 스트리밍한다.

    yield: `app.live.events` 계약의 프레임들(step/log/screenshot/hitl/chat/transactions),
           그리고 최종 result/error. 그래프가 state 에 result/error 만 남기고 이벤트를 안
           내면 여기서 최종 프레임을 방출한다(노드가 이미 냈으면 중복 없이 종료).
    """
    creds = creds or {}
    events: asyncio.Queue = asyncio.Queue()
    limiter = semaphore or contextlib.nullcontext()
    async with limiter:
        browser = await browser_factory()
        try:
            page = await browser.new_page()
        except Exception:
            logger.warning("run_workflow: new_page 실패 — 페이지 없이 진행")
            page = None

        state: dict = {
            "page": page,
            "browser": browser,
            "events": events,
            "userid": creds.get("userid"),
            "password": creds.get("password"),
            "params": params or {},
        }

        async def runner() -> None:
            try:
                final = await graph.ainvoke(state)
                await events.put({"_final": final or {}})
            except Exception:
                logger.exception("workflow run failed")
                await events.put({"_final": {"error": "실행 중 오류(워크플로우/브라우저)."}})

        task = asyncio.create_task(runner())
        cast: asyncio.Task | None = None
        if screencast and page is not None:
            cast = asyncio.create_task(screencast_pump(page, events))
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
            if cast is not None:
                cast.cancel()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("runner task 종료 예외 무시", exc_info=True)
            try:
                await browser.close()
            except Exception:
                logger.debug("browser.close 예외 무시", exc_info=True)
