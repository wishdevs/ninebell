"""/runs 라우터 테스트 — SSE 수집 라우트 형태 + HITL 응답 + AgentRun 영속.

브라우저는 fake browser_factory(app.state override)로 대체하고, 워크플로우는 events 큐만
쓰는 fake 그래프를 등록해 실제 헤드리스 브라우저 없이 SSE happy path 까지 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.live import store
from app.live.hitl import _hitl_queues, set_hitl_owner
from app.live.registry import register_workflow
from app.main import app as fastapi_app


class _FakeGraph:
    """events 큐에 step/log 를 넣고 result 를 반환하는 fake 그래프(브라우저 미사용)."""

    async def ainvoke(self, state: dict) -> dict:
        ev = state["events"]
        await ev.put({"step": "테스트", "status": "running"})
        await ev.put({"log": "hi", "level": "info"})
        await ev.put({"step": "테스트", "status": "done"})
        return {"result": "ok"}


class _FakeBrowser:
    async def new_page(self):
        return None  # page None → screencast 스킵, 페이지 조작 없음

    async def close(self):
        return None


async def _fake_browser_factory():
    return _FakeBrowser()


@pytest.mark.asyncio
async def test_collect_requires_auth(client):
    r = await client.post("/runs/collect", json={"agentId": "demo-echo"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_collect_unknown_workflow_404(client, make_user, auth_as):
    uid = await make_user("alice", "user")
    auth_as(uid)
    r = await client.post("/runs/collect", json={"agentId": "does-not-exist"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_collect_resume_gone_returns_410(client, make_user, auth_as):
    uid = await make_user("bob", "user")
    auth_as(uid)
    # runId 있고 cursor>0 인데 세션이 없다 → 흐름 종료(410).
    r = await client.post(
        "/runs/collect", json={"runId": "run-missing", "agentId": "demo-echo", "cursor": 3}
    )
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_collect_sse_happy_path(client, make_user, auth_as):
    uid = await make_user("carol", "user")
    auth_as(uid)
    register_workflow("test-echo", lambda: _FakeGraph())
    fastapi_app.state.browser_factory = _fake_browser_factory
    # runId 없음 → 익명 세션(DB 영속 없이 SSE 형태만 검증).
    r = await client.post("/runs/collect", json={"agentId": "test-echo"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert '"step": "\\ud14c\\uc2a4\\ud2b8"' in body or '"step": "테스트"' in body
    assert '"result": "ok"' in body
    assert "[DONE]" in body


@pytest.mark.asyncio
async def test_hitl_unknown_decision_returns_not_resolved(client, make_user, auth_as):
    uid = await make_user("dave", "user")
    auth_as(uid)
    r = await client.post("/runs/hitl", json={"decisionId": "nope"})
    assert r.status_code == 200
    assert r.json() == {"ok": False}


@pytest.mark.asyncio
async def test_hitl_owner_mismatch_forbidden(client, make_user, auth_as):
    uid = await make_user("erin", "user")
    auth_as(uid)
    set_hitl_owner("dec-other", "someone-else")
    _hitl_queues["dec-other"] = asyncio.Queue()
    try:
        r = await client.post("/runs/hitl", json={"decisionId": "dec-other"})
        assert r.status_code == 403
    finally:
        _hitl_queues.pop("dec-other", None)


@pytest.mark.asyncio
async def test_hitl_resolves_owned_decision(client, make_user, auth_as):
    uid = await make_user("frank", "user")
    auth_as(uid)
    q: asyncio.Queue = asyncio.Queue()
    _hitl_queues["dec-frank"] = q
    set_hitl_owner("dec-frank", str(uid))
    try:
        r = await client.post("/runs/hitl", json={"decisionId": "dec-frank", "value": "yes"})
        assert r.json() == {"ok": True}
        payload = q.get_nowait()
        assert payload["value"] == "yes"
    finally:
        _hitl_queues.pop("dec-frank", None)


@pytest.mark.asyncio
async def test_agent_run_persistence_roundtrip(make_user):
    uid = await make_user("grace", "user")
    await store.create_run(run_id="run-persist", agent_id="demo-echo", user_id=uid)
    run = await store.get_run("run-persist")
    assert run is not None
    assert run.status == "running"
    assert str(run.user_id) == str(uid)

    logs = [{"ts": 1, "level": "ok", "message": "done"}]
    await store.set_terminal("run-persist", "succeeded", "결과", logs)
    run2 = await store.get_run("run-persist")
    assert run2.status == "succeeded"
    assert run2.result == "결과"
    assert run2.finished_at is not None
    assert run2.logs == logs
