"""LiveSession 커서/버퍼/재연결/리퍼 단위 테스트 — FAKE async producer(브라우저 없음).

세션의 스트리밍 로직(버퍼 재생, 커서 재접속, 스크린샷 최신1장, 종료 콜백, HITL 소유권,
리퍼 grace)을 실제 브라우저/그래프 없이 검증한다.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.live import session as S
from app.live.hitl import hitl_owner
from app.live.session import LiveSession


async def _noop_terminal(status, note, logs) -> None:  # 기본 on_terminal
    return None


async def _drain(sess: LiveSession, cursor: int = 0) -> list[dict]:
    return [ev async for ev in sess.stream(cursor)]


@pytest.mark.asyncio
async def test_cursor_replay_from_zero():
    async def producer():
        for i in range(3):
            yield {"step": f"s{i}", "status": "done"}
        yield {"result": "ok"}

    sess = LiveSession("k1", None, lambda: producer(), _noop_terminal)
    sess.start()
    got = await _drain(sess, 0)
    assert got == [
        {"step": "s0", "status": "done"},
        {"step": "s1", "status": "done"},
        {"step": "s2", "status": "done"},
        {"result": "ok"},
    ]


@pytest.mark.asyncio
async def test_cursor_resume_replays_tail():
    async def producer():
        for i in range(3):
            yield {"log": str(i), "level": "info"}
        yield {"result": "ok"}

    sess = LiveSession("k2", None, lambda: producer(), _noop_terminal)
    sess.start()
    await _drain(sess, 0)  # 흐름 종료까지 소비 → 버퍼 4개
    tail = await _drain(sess, 2)  # 커서 2 이후만 재생
    assert tail == [{"log": "2", "level": "info"}, {"result": "ok"}]


@pytest.mark.asyncio
async def test_screenshot_is_latest_only_not_buffered():
    async def producer():
        yield {"step": "a", "status": "running"}
        yield {"screenshot": "data:image/jpeg;base64,AAA"}
        yield {"screenshot": "data:image/jpeg;base64,BBB"}
        yield {"result": "ok"}

    sess = LiveSession("k3", None, lambda: producer(), _noop_terminal)
    sess.start()
    got = await _drain(sess, 0)
    # 버퍼(커서 대상)엔 스크린샷이 없다.
    assert all("screenshot" not in ev for ev in sess.buffer)
    assert sess.buffer == [{"step": "a", "status": "running"}, {"result": "ok"}]
    assert sess.shot_seq == 2
    # 스트림엔 최신 화면 1장(BBB)이 흘렀다(밀린 프레임은 합쳐짐).
    shots = [ev for ev in got if "screenshot" in ev]
    assert shots and shots[-1]["screenshot"].endswith("BBB")


@pytest.mark.asyncio
async def test_reconnect_after_disconnect_resumes():
    gate = asyncio.Event()

    async def producer():
        yield {"log": "1", "level": "info"}
        yield {"log": "2", "level": "info"}
        await gate.wait()  # 첫 구독자가 끊길 시간을 준다(흐름은 계속 산다)
        yield {"log": "3", "level": "info"}
        yield {"log": "4", "level": "info"}
        yield {"result": "ok"}

    sess = LiveSession("k4", "alice", lambda: producer(), _noop_terminal)
    sess.start()

    got1: list[dict] = []
    agen = sess.stream(0)
    async for ev in agen:  # 2개 받고 '끊김'
        got1.append(ev)
        if len(got1) == 2:
            break
    await agen.aclose()  # 클라 disconnect = 구독 제너레이터 종료(흐름은 무관)
    assert [e["log"] for e in got1] == ["1", "2"]
    assert sess.subscribers == 0  # detached — 흐름은 여전히 살아있음
    assert not sess.terminal

    gate.set()  # 흐름 진행 재개
    got2 = await _drain(sess, 2)  # 재연결: 커서 2 이후만
    assert [e.get("log") for e in got2 if "log" in e] == ["3", "4"]
    assert got2[-1] == {"result": "ok"}


@pytest.mark.asyncio
async def test_on_terminal_receives_final_status_and_logs():
    captured: dict = {}

    async def on_terminal(status, note, logs) -> None:
        captured.update(status=status, note=note, logs=logs)

    async def producer():
        yield {"log": "hello", "level": "info"}
        yield {"step": "work", "status": "done"}
        yield {"result": "done"}

    sess = LiveSession("k5", None, lambda: producer(), on_terminal)
    sess.start()
    await _drain(sess, 0)
    await asyncio.wait_for(sess._pump, timeout=2)  # 펌프 finally(on_terminal) 완료 대기
    assert captured["status"] == "succeeded"
    assert captured["note"] == "done"
    assert any(line["message"] == "hello" for line in captured["logs"])


@pytest.mark.asyncio
async def test_error_event_marks_failed_terminal():
    captured: dict = {}

    async def on_terminal(status, note, logs) -> None:
        captured.update(status=status, note=note)

    async def producer():
        yield {"error": "boom"}

    sess = LiveSession("k6", None, lambda: producer(), on_terminal)
    sess.start()
    got = await _drain(sess, 0)
    await asyncio.wait_for(sess._pump, timeout=2)
    assert got == [{"error": "boom"}]
    assert captured["status"] == "failed"
    assert captured["note"] == "boom"


@pytest.mark.asyncio
async def test_hitl_owner_registered_for_owned_session():
    async def producer():
        yield {"hitl": {"id": "dec-owned", "kind": "confirm", "title": "t", "prompt": "p"}}
        yield {"result": "ok"}

    sess = LiveSession("k7", "alice", lambda: producer(), _noop_terminal)
    sess.start()
    await _drain(sess, 0)
    assert hitl_owner("dec-owned") == "alice"


@pytest.mark.asyncio
async def test_reaper_collects_detached_terminal_session():
    async def producer():
        yield {"result": "ok"}

    sess = S.create_session("reapme", "alice", lambda: producer(), _noop_terminal)
    await _drain(sess, 0)
    await asyncio.wait_for(sess._pump, timeout=2)
    assert sess.terminal and sess.subscribers == 0
    # grace 를 넘긴 것처럼 detached 시각을 과거로 밀고 리퍼 1회 실행.
    sess.detached_at = time.monotonic() - (S.TERMINAL_GRACE_S + 1)
    await S._reap_once()
    assert S.get_session("reapme") is None


async def _wait_buffered(sess: LiveSession, n: int = 1, tries: int = 100) -> None:
    """펌프가 버퍼에 최소 n개 이벤트를 넣을 때까지 잠깐 대기(취소 전 진행 보장)."""
    for _ in range(tries):
        if len(sess.buffer) >= n:
            return
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancel_marks_cancelled_terminal():
    captured: dict = {}
    gate = asyncio.Event()

    async def on_terminal(status, note, logs) -> None:
        captured.update(status=status, note=note)

    async def producer():
        yield {"step": "work", "status": "running"}
        await gate.wait()  # 취소로만 끝난다(정상 완료 없음)
        yield {"result": "should-not-reach"}

    sess = LiveSession("cancelme", "alice", lambda: producer(), on_terminal)
    sess.start()
    await _wait_buffered(sess, 1)
    await sess.cancel()  # 즉시 종료 — cancelled 로 확정
    assert sess.terminal
    assert captured["status"] == "cancelled"
    # 정상 result 프레임은 방출되지 않았다(취소가 producer 를 끊음).
    assert all("result" not in ev for ev in sess.buffer)


@pytest.mark.asyncio
async def test_cancel_is_idempotent_on_terminal_session():
    async def producer():
        yield {"result": "ok"}

    sess = LiveSession("cxl-done", None, lambda: producer(), _noop_terminal)
    sess.start()
    await _drain(sess, 0)
    await asyncio.wait_for(sess._pump, timeout=2)
    assert sess.terminal and sess._final_status == "succeeded"
    await sess.cancel()  # 이미 종료 → no-op(성공 상태 덮어쓰지 않음)
    assert sess._final_status == "succeeded"


@pytest.mark.asyncio
async def test_cancel_session_helper_cancels_and_removes():
    gate = asyncio.Event()

    async def producer():
        yield {"step": "x", "status": "running"}
        await gate.wait()

    sess = S.create_session("cs1", "alice", lambda: producer(), _noop_terminal)
    await _wait_buffered(sess, 1)
    assert await S.cancel_session("cs1") is True
    assert S.get_session("cs1") is None  # 즉시 레지스트리에서 제거
    assert sess.terminal
    # 없는 키는 멱등 False(호출자가 200 처리).
    assert await S.cancel_session("does-not-exist") is False
    assert await S.cancel_session(None) is False
