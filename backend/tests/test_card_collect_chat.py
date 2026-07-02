"""P1-B 대화형 HITL 지속 채널 — 처리 중 사용자 입력 유실 방지.

기존 결함: 노드가 매 턴 새 wait_hitl 큐를 만들어, 턴 사이(Gemini 판단·브라우저 조작 중)에는
살아있는 큐가 없어 그때 도착한 사용자 메시지·'선택 완료'가 resolve_hitl False → 영구 유실됐다.
지속 채널(open/close_hitl_channel)은 노드 수명 내내 큐를 유지해 그 사이 입력을 버퍼링한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.live.hitl import (
    close_hitl_channel,
    hitl_owner,
    open_hitl_channel,
    resolve_hitl,
    set_hitl_owner,
)


async def test_persistent_channel_buffers_messages_during_processing():
    """처리 중(큐를 아직 안 읽는 동안) 도착한 2개 메시지가 순서대로 모두 보존된다."""
    did = "dec-1"
    q = open_hitl_channel(did)
    try:
        # 노드가 브라우저 조작 중이라 아직 q.get() 을 호출하지 않은 상황을 흉내낸다.
        assert resolve_hitl(did, {"message": "1번 경영 처리"}) is True
        assert resolve_hitl(did, {"message": "2번 건너뛰어"}) is True
        assert resolve_hitl(did, {"done": True}) is True

        # 이제 노드가 순차적으로 큐를 소진 — 유실 없이 순서 보존.
        first = await asyncio.wait_for(q.get(), timeout=1)
        second = await asyncio.wait_for(q.get(), timeout=1)
        third = await asyncio.wait_for(q.get(), timeout=1)
        assert first == {"message": "1번 경영 처리"}
        assert second == {"message": "2번 건너뛰어"}
        assert third == {"done": True}
    finally:
        close_hitl_channel(did)


def test_resolve_before_open_is_lost_but_after_open_survives():
    """채널 오픈 전 resolve 는 False(대상 없음), 오픈 후에는 True — 회귀 방지 대조."""
    did = "dec-2"
    assert resolve_hitl(did, {"message": "too early"}) is False  # 오픈 전엔 대상 없음
    open_hitl_channel(did)
    try:
        assert resolve_hitl(did, {"message": "now buffered"}) is True
    finally:
        close_hitl_channel(did)


def test_close_channel_cleans_up_queue_and_owner():
    did = "dec-3"
    open_hitl_channel(did)
    set_hitl_owner(did, "user-42")
    assert hitl_owner(did) == "user-42"
    close_hitl_channel(did)
    # 종료 후엔 resolve 불가(큐 제거) + 소유권 제거.
    assert resolve_hitl(did, {"message": "late"}) is False
    assert hitl_owner(did) is None


async def test_wait_hitl_uses_config_timeout_when_none(monkeypatch):
    """wait_hitl(timeout_s=None) 은 config.hitl_timeout_s(단일 소스)를 쓴다."""
    import app.live.hitl as hitl_mod

    captured: dict = {}

    async def _fake_wait_for(coro, timeout):
        captured["timeout"] = timeout
        coro.close()  # 대기 코루틴 정리(실제로 기다리지 않음)
        return {"done": True}

    monkeypatch.setattr(hitl_mod.asyncio, "wait_for", _fake_wait_for)
    events: asyncio.Queue = asyncio.Queue()
    await hitl_mod.wait_hitl(events, kind="chat", title="t", prompt="p", timeout_s=None)
    assert captured["timeout"] == hitl_mod.get_settings().hitl_timeout_s
