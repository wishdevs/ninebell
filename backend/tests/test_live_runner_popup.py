"""리뷰 HIGH-3 / MEDIUM — 자식 창(팝업) 라이프사이클 + 스테일 프레임 방어.

fake Playwright context/page 더블로 팝업이 열리고("page" 이벤트) 닫히는("close" 이벤트)
과정을 결정적으로 재현한다. 검증:
  - 자식 스크린캐스트 펌프가 생성돼 자식 프레임(window=child)이 흐른다.
  - 닫힘 시 펌프가 취소되고 {"window":"child","closed":true} 전이가 방출된다.
  - 닫힌 뒤 늦게 도착한 CDP 프레임(인플라이트)은 자식 슬롯을 되살리지 않는다(HIGH-3 가드).
  - teardown 에서 context.on("page") 리스너가 제거된다(MEDIUM — 늦은 펌프 유출 방지).
"""

from __future__ import annotations

import asyncio

import pytest

from app.live.runner import CHILD_VIEWPORT, run_workflow
from app.live.screencast import screencast_pump


# ── fake Playwright 더블 ─────────────────────────────────────────────────────
class FakeCDP:
    """CDP 세션 더블 — on_frame 콜백을 저장하고, fire_frame 으로 프레임을 수동 주입한다."""

    def __init__(self) -> None:
        self._on: dict = {}
        self.started = asyncio.Event()  # startScreencast 도달 신호(결정적 동기화)
        self.stopped = False

    def on(self, event: str, cb) -> None:
        self._on[event] = cb

    async def send(self, method: str, params: dict | None = None):
        if method == "Page.startScreencast":
            self.started.set()
        elif method == "Page.stopScreencast":
            self.stopped = True
        return None

    def fire_frame(self, data: str) -> None:
        cb = self._on.get("Page.screencastFrame")
        if cb is not None:
            cb({"data": data, "sessionId": "sess"})


class FakePage:
    def __init__(self, context: "FakeContext") -> None:
        self.context = context
        self.cdp = FakeCDP()
        self._closed = False
        self._close_cbs: list = []
        self.viewport: dict | None = None  # set_viewport_size 기록(자식창 뷰포트 강제 검증)

    def is_closed(self) -> bool:
        return self._closed

    async def set_viewport_size(self, viewport: dict) -> None:
        self.viewport = viewport

    def on(self, event: str, cb) -> None:
        if event == "close":
            self._close_cbs.append(cb)

    def close_now(self) -> None:
        self._closed = True
        for cb in list(self._close_cbs):
            cb()


class FakeContext:
    def __init__(self) -> None:
        self._page_handlers: list = []
        self.removed: list = []

    def on(self, event: str, cb) -> None:
        if event == "page":
            self._page_handlers.append(cb)

    def remove_listener(self, event: str, cb) -> None:
        if event == "page":
            self.removed.append(cb)
            self._page_handlers = [h for h in self._page_handlers if h is not cb]

    async def new_cdp_session(self, page: FakePage) -> FakeCDP:
        return page.cdp

    def fire_new_page(self, page: FakePage) -> None:
        for h in list(self._page_handlers):
            h(page)

    async def storage_state(self) -> dict:
        return {}


class FakeBrowser:
    def __init__(self, parent: FakePage) -> None:
        self._parent = parent
        self.closed = False

    async def new_page(self, viewport=None) -> FakePage:
        return self._parent

    async def close(self) -> None:
        self.closed = True


# ── HIGH-3: screencast_pump 가드(닫힌 뒤 프레임 드롭) 직접 검증 ────────────────
@pytest.mark.asyncio
async def test_screencast_pump_drops_frames_after_page_closed():
    events: asyncio.Queue = asyncio.Queue()
    page = FakePage(FakeContext())
    task = asyncio.create_task(screencast_pump(page, events, window="child"))
    await page.cdp.started.wait()  # startScreencast 까지 진행(on_frame 등록 완료)

    page.cdp.fire_frame("LIVE")
    frame = events.get_nowait()
    assert frame["window"] == "child"
    assert frame["screenshot"].endswith("LIVE")

    # 페이지 닫힘 후 늦게 도착한 프레임은 무시(HIGH-3) — 큐가 다시 채워지지 않는다.
    page._closed = True
    page.cdp.fire_frame("STALE")
    assert events.empty()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── MEDIUM/HIGH-3: run_workflow 팝업 라이프사이클(생성→닫힘→늦은프레임→리스너제거) ──
class PopupGraph:
    """실행 중 팝업을 열고, 자식 프레임 → 닫힘 → 늦은 프레임을 결정적으로 재현하는 fake 그래프."""

    def __init__(self, ctx: FakeContext) -> None:
        self._ctx = ctx
        self.child: FakePage | None = None

    async def ainvoke(self, state: dict) -> dict:
        child = FakePage(self._ctx)
        self.child = child
        self._ctx.fire_new_page(child)  # _on_new_page(child): 자식 펌프 생성 + close 핸들러 등록
        await child.cdp.started.wait()  # 자식 펌프가 on_frame 을 등록할 때까지(결정적)
        child.cdp.fire_frame("CHILD")  # 자식 스크린샷 프레임(window=child)
        child.close_now()  # child_cast 취소 + {"window":"child","closed":true} 방출, is_closed=True
        child.cdp.fire_frame("LATE")  # 닫힘 뒤 늦은 프레임 → 가드로 드롭
        return {"result": "ok"}


@pytest.mark.asyncio
async def test_run_workflow_child_popup_lifecycle():
    ctx = FakeContext()
    parent = FakePage(ctx)

    async def _factory() -> FakeBrowser:
        return FakeBrowser(parent)

    graph = PopupGraph(ctx)
    frames = [
        ev
        async for ev in run_workflow(
            graph, _factory, {"userid": None}, {}, login_form_selector=None
        )
    ]

    # 자식 펌프가 생성돼 자식 스크린샷(window=child)이 흘렀다.
    child_shots = [ev for ev in frames if ev.get("window") == "child" and "screenshot" in ev]
    assert child_shots and child_shots[-1]["screenshot"].endswith("CHILD")
    # 자식 팝업 뷰포트를 세로로 큰 전용 크기로 강제해야 결제 폼이 잘리지 않는다(캡처 전 리사이즈).
    assert graph.child is not None and graph.child.viewport == CHILD_VIEWPORT
    # 닫힘 전이 프레임이 방출됐다(펌프 취소 경로 실행 증거).
    assert {"window": "child", "closed": True} in frames
    # 닫힌 뒤 늦은 프레임은 자식 슬롯을 되살리지 않는다(스트림에 LATE 없음).
    assert not [ev for ev in frames if "LATE" in (ev.get("screenshot") or "")]
    # 종료(성공) 프레임.
    assert {"result": "ok"} in frames
    # teardown 에서 팝업 리스너가 제거됐다(MEDIUM).
    assert ctx.removed, "context.remove_listener('page') 가 teardown 에서 호출돼야 한다"
