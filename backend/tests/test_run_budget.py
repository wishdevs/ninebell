"""런 전역 활동 시간 예산 — 추적기 단위 + 러너 워치독 + HITL 대기 제외 정책.

run_budget(추적기)은 가짜 시계(_now monkeypatch)로 결정적으로 검증하고, 러너 워치독은
fake 브라우저/그래프 더블 + 짧은 예산(settings monkeypatch)으로 초과 중단·80% 경고·
비활성(budget=0)·미초과 무영향·HITL 대기 미소모를 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.live import run_budget, runner
from app.live.hitl import open_hitl_channel, resolve_hitl, wait_hitl
from app.live.runner import run_workflow
from app.live.session import LiveSession


# ── 가짜 시계 ────────────────────────────────────────────────────────────────
class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@pytest.fixture()
def clock(monkeypatch) -> FakeClock:
    c = FakeClock()
    monkeypatch.setattr(run_budget, "_now", c)
    return c


@pytest.fixture(autouse=True)
def _clean_budgets():
    run_budget._budgets.clear()
    yield
    run_budget._budgets.clear()


# ── ① 추적기 단위(가짜 시계) ─────────────────────────────────────────────────
def test_active_elapsed_grows_with_clock(clock: FakeClock):
    run_budget.start("r1")
    clock.advance(10)
    assert run_budget.active_elapsed("r1") == pytest.approx(10.0)


def test_pause_excludes_wait_time(clock: FakeClock):
    run_budget.start("r1")
    clock.advance(5)
    run_budget.pause("r1")
    clock.advance(100)  # HITL 대기 100s — 예산 미소모
    assert run_budget.active_elapsed("r1") == pytest.approx(5.0)
    run_budget.resume("r1")
    clock.advance(3)
    assert run_budget.active_elapsed("r1") == pytest.approx(8.0)


def test_nested_pause_resume_is_safe(clock: FakeClock):
    run_budget.start("r1")
    clock.advance(2)
    run_budget.pause("r1")
    run_budget.pause("r1")  # 중첩
    clock.advance(50)
    run_budget.resume("r1")  # 아직 1겹 남음 — 여전히 정지
    clock.advance(50)
    assert run_budget.active_elapsed("r1") == pytest.approx(2.0)
    run_budget.resume("r1")  # 마지막 겹 해제 — 재개
    clock.advance(4)
    assert run_budget.active_elapsed("r1") == pytest.approx(6.0)
    # 과잉 resume 은 no-op(깊이 0 미만으로 내려가지 않는다).
    run_budget.resume("r1")
    clock.advance(1)
    assert run_budget.active_elapsed("r1") == pytest.approx(7.0)


def test_unknown_run_id_noops(clock: FakeClock):
    assert run_budget.active_elapsed("nope") == 0.0
    run_budget.pause("nope")
    run_budget.resume("nope")
    run_budget.clear("nope")  # 멱등
    assert run_budget.active_elapsed(None) == 0.0
    run_budget.pause(None)
    run_budget.resume(None)
    run_budget.clear(None)


def test_clear_removes_and_start_resets(clock: FakeClock):
    run_budget.start("r1")
    clock.advance(9)
    run_budget.clear("r1")
    assert run_budget.active_elapsed("r1") == 0.0
    run_budget.start("r1")  # 재시작 — 누적 리셋
    clock.advance(1)
    assert run_budget.active_elapsed("r1") == pytest.approx(1.0)


# ── ③ HITL 대기 중 예산 미소모(pause 반영) ──────────────────────────────────
@pytest.mark.asyncio
async def test_open_hitl_channel_get_pauses_budget(clock: FakeClock):
    run_budget.start("run-h1")
    q = open_hitl_channel("dec-h1", owner="alice", run_id="run-h1")
    waiter = asyncio.create_task(q.get())
    await asyncio.sleep(0.01)  # get() 진입(pause) 보장
    clock.advance(500)  # 사용자 고민 500s — 활동 시간에 안 잡힌다
    assert run_budget.active_elapsed("run-h1") == pytest.approx(0.0)
    assert resolve_hitl("dec-h1", {"action": "ok"}) is True
    assert await waiter == {"action": "ok"}
    clock.advance(7)  # 재개 후 활동은 다시 잡힌다
    assert run_budget.active_elapsed("run-h1") == pytest.approx(7.0)


@pytest.mark.asyncio
async def test_wait_hitl_pauses_budget(clock: FakeClock):
    run_budget.start("run-h2")
    events: asyncio.Queue = asyncio.Queue()
    waiter = asyncio.create_task(
        wait_hitl(events, kind="confirm", title="t", prompt="p", run_id="run-h2")
    )
    frame = await asyncio.wait_for(events.get(), timeout=2)
    await asyncio.sleep(0.01)  # q.get() 진입(pause) 보장
    clock.advance(500)
    assert run_budget.active_elapsed("run-h2") == pytest.approx(0.0)
    assert resolve_hitl(frame["hitl"]["id"], {"action": "ok"}) is True
    assert await waiter == {"action": "ok"}
    clock.advance(3)
    assert run_budget.active_elapsed("run-h2") == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_wait_hitl_timeout_resumes_budget(clock: FakeClock):
    """타임아웃(취소)으로 get() 이 중단돼도 finally 로 resume 이 보장된다."""
    run_budget.start("run-h3")
    events: asyncio.Queue = asyncio.Queue()
    with pytest.raises(asyncio.TimeoutError):
        await wait_hitl(
            events, kind="confirm", title="t", prompt="p", run_id="run-h3", timeout_s=0.01
        )
    clock.advance(5)  # 재개됐으면 활동이 다시 흐른다(pause 잔류 없음)
    assert run_budget.active_elapsed("run-h3") == pytest.approx(5.0)


# ── 러너 워치독용 fake 더블(브라우저/페이지 — 스크린캐스트 미사용) ─────────────
class FakeContext:
    def on(self, event: str, cb) -> None:
        pass

    def remove_listener(self, event: str, cb) -> None:
        pass


class FakePage:
    def __init__(self) -> None:
        self.context = FakeContext()
        self.shot_taken = False

    async def screenshot(self, **kwargs) -> bytes:
        self.shot_taken = True
        return b"JPEGDATA"


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self._page = page
        self.closed = False

    async def new_page(self, viewport=None) -> FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


class HangGraph:
    """무한히 도는 그래프 — 예산 초과 취소 대상."""

    def __init__(self) -> None:
        self.cancelled = False

    async def ainvoke(self, state: dict) -> dict:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {"result": "unreachable"}


class QuickGraph:
    """즉시 성공하는 그래프 — 미초과 정상 종료 무영향 검증."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self._delay_s = delay_s

    async def ainvoke(self, state: dict) -> dict:
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        return {"result": "ok"}


def _budget_env(monkeypatch, budget_s: float, interval_s: float = 0.01) -> None:
    """짧은 예산·체크 간격으로 워치독을 빠르게 돌린다(테스트 전용 노브)."""
    monkeypatch.setattr(get_settings(), "run_active_budget_s", budget_s)
    monkeypatch.setattr(runner, "_BUDGET_CHECK_INTERVAL_S", interval_s)


async def _run(graph, browser: FakeBrowser, run_id: str | None) -> list[dict]:
    async def _factory() -> FakeBrowser:
        return browser

    return [
        ev
        async for ev in run_workflow(
            graph,
            _factory,
            {"userid": None},
            {},
            run_id=run_id,
            screencast=False,
            login_form_selector=None,
        )
    ]


# ── ② 워치독 — 초과 시 failed+사유·clear 보장, 미초과 무영향, budget=0 비활성 ──
@pytest.mark.asyncio
async def test_watchdog_cancels_over_budget_run(monkeypatch):
    _budget_env(monkeypatch, budget_s=0.05)
    graph = HangGraph()
    page = FakePage()
    browser = FakeBrowser(page)
    frames = await asyncio.wait_for(_run(graph, browser, "run-w1"), timeout=5)

    # 초과 사유가 error 로그 + 최종 error 프레임으로 방출된다.
    err_logs = [ev for ev in frames if "런 시간 예산 초과" in str(ev.get("log"))]
    assert err_logs and err_logs[0]["level"] == "error"
    assert frames[-1] == {"error": err_logs[0]["log"]}
    # best-effort 마지막 스크린샷 1장.
    assert page.shot_taken
    assert any("screenshot" in ev for ev in frames)
    # 그래프 태스크는 취소됐고, 브라우저는 finally 에서 닫혔다(기존 teardown 경로).
    assert graph.cancelled
    assert browser.closed
    # 종료 경로에서 예산 추적이 정리됐다(clear 보장).
    assert run_budget._budgets == {}


@pytest.mark.asyncio
async def test_watchdog_warns_once_at_80_percent(monkeypatch):
    _budget_env(monkeypatch, budget_s=0.3, interval_s=0.02)
    frames = await asyncio.wait_for(
        _run(HangGraph(), FakeBrowser(FakePage()), "run-w2"), timeout=5
    )
    warns = [ev for ev in frames if "예산 80% 소진" in str(ev.get("log"))]
    assert len(warns) == 1  # 여러 틱을 지나도 경고는 1회
    assert warns[0]["level"] == "warn"
    # 경고가 초과 error 보다 먼저 온다.
    assert frames.index(warns[0]) < frames.index(
        next(ev for ev in frames if "error" in ev)
    )


@pytest.mark.asyncio
async def test_watchdog_terminal_path_marks_failed(monkeypatch):
    """세션 펌프까지 통과 — on_terminal 이 failed + 초과 사유로 확정된다(기존 규약)."""
    _budget_env(monkeypatch, budget_s=0.05)
    captured: dict = {}

    async def on_terminal(status, note, logs) -> None:
        captured.update(status=status, note=note)

    sess = LiveSession(
        "budget-sess",
        "alice",
        lambda: run_workflow(
            HangGraph(),
            _make_factory(FakeBrowser(FakePage())),
            {"userid": None},
            {},
            run_id="run-w3",
            screencast=False,
            login_form_selector=None,
        ),
        on_terminal,
    )
    sess.start()
    [ev async for ev in sess.stream(0)]
    await asyncio.wait_for(sess._pump, timeout=5)
    assert captured["status"] == "failed"
    assert "런 시간 예산 초과" in captured["note"]
    assert run_budget._budgets == {}


def _make_factory(browser: FakeBrowser):
    async def _factory() -> FakeBrowser:
        return browser

    return _factory


@pytest.mark.asyncio
async def test_budget_zero_disables_watchdog(monkeypatch):
    _budget_env(monkeypatch, budget_s=0)
    started: list = []
    monkeypatch.setattr(run_budget, "start", lambda rid: started.append(rid))
    frames = await asyncio.wait_for(
        _run(QuickGraph(delay_s=0.05), FakeBrowser(FakePage()), "run-w4"), timeout=5
    )
    assert frames == [{"result": "ok"}]  # 예산보다 오래 걸려도(비활성) 정상 종료
    assert started == []  # 추적 자체를 시작하지 않는다(현행 동작)


@pytest.mark.asyncio
async def test_under_budget_run_unaffected(monkeypatch):
    _budget_env(monkeypatch, budget_s=100)
    browser = FakeBrowser(FakePage())
    frames = await asyncio.wait_for(_run(QuickGraph(), browser, "run-w5"), timeout=5)
    assert frames == [{"result": "ok"}]
    assert not any("예산" in str(ev.get("log")) for ev in frames)
    assert browser.closed
    assert run_budget._budgets == {}  # 정상 종료 경로에서도 clear


@pytest.mark.asyncio
async def test_missing_run_id_skips_watchdog(monkeypatch):
    """run_id 없음(스크립트/익명) — 추적 키가 없어 워치독 미기동(기존 경로 무영향)."""
    _budget_env(monkeypatch, budget_s=0.05)
    frames = await asyncio.wait_for(
        _run(QuickGraph(delay_s=0.1), FakeBrowser(FakePage()), None), timeout=5
    )
    assert frames == [{"result": "ok"}]
    assert run_budget._budgets == {}


class HitlGraph:
    """HITL 대기(wait_hitl)로 사용자 응답을 기다렸다 성공하는 그래프."""

    async def ainvoke(self, state: dict) -> dict:
        await wait_hitl(
            state["events"],
            kind="confirm",
            title="확인",
            prompt="계속할까요?",
            run_id=state.get("run_id"),
        )
        return {"result": "resumed"}


@pytest.mark.asyncio
async def test_hitl_wait_does_not_consume_budget(monkeypatch):
    """예산(0.05s)보다 훨씬 긴 HITL 대기(0.2s)에도 워치독이 발화하지 않는다(pause 정책)."""
    _budget_env(monkeypatch, budget_s=0.05)
    browser = FakeBrowser(FakePage())
    frames: list[dict] = []

    async def _collect() -> None:
        async for ev in run_workflow(
            HitlGraph(),
            _make_factory(browser),
            {"userid": None},
            {},
            run_id="run-w6",
            screencast=False,
            login_form_selector=None,
        ):
            frames.append(ev)

    collector = asyncio.create_task(_collect())
    # hitl 프레임이 흐를 때까지 대기 → 예산 한도를 훌쩍 넘겨 사용자 고민을 재현.
    for _ in range(200):
        if any("hitl" in ev for ev in frames):
            break
        await asyncio.sleep(0.01)
    hitl_frame = next(ev for ev in frames if "hitl" in ev)
    await asyncio.sleep(0.2)  # 예산 4배 대기 — pause 로 예산 미소모여야 한다
    assert resolve_hitl(hitl_frame["hitl"]["id"], {"action": "ok"}) is True
    await asyncio.wait_for(collector, timeout=5)
    assert {"result": "resumed"} in frames  # 초과 중단 없이 정상 성공
    assert not any("런 시간 예산 초과" in str(ev.get("log")) for ev in frames)
    assert run_budget._budgets == {}
