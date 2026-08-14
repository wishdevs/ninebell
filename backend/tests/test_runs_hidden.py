"""리뷰 HIGH-1 — 숨김(검증 전) 에이전트는 라이브 실행이 차단된다(관리자만 허용).

runs.collect 는 workflow_id 로 Agent 를 역조회한 뒤, 그 id 가 _HIDDEN_AGENT_IDS(agents.py 목록/
상세 숨김과 동일 소스)에 있으면 비관리자에게 403 을 준다. 관리자는 게이트 스모크를 위해 통과.
숨김이 아닌 에이전트는 불변(정상 200).

⚠ 게이트 '로직' 만 검증하려고 **합성 숨김 id** 를 runs 가 참조하는 _HIDDEN_AGENT_IDS 에 monkeypatch
로 주입한다 — 어떤 실제 픽스처가 숨김이든(노출/게이트 결정이 바뀌든) 이 테스트는 무관하게 그대로다.
"""

from __future__ import annotations

import pytest

import app.routers.runs as runs_mod
from app.live.registry import register_workflow
from app.main import app as fastapi_app

VISIBLE_WF = "gated-wf"
HIDDEN_WF = "gated-wf-hidden"
HIDDEN_AGENT_ID = "a-gated-hidden"


class _FakeGraph:
    async def ainvoke(self, state: dict) -> dict:
        await state["events"].put({"step": "s", "status": "done"})
        return {"result": "ok"}


class _FakeBrowser:
    async def new_page(self, **kw):
        return None  # page None → 스크린캐스트/페이지 조작 스킵

    async def close(self):
        return None


async def _fake_browser_factory():
    return _FakeBrowser()


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    register_workflow(VISIBLE_WF, lambda: _FakeGraph())
    register_workflow(HIDDEN_WF, lambda: _FakeGraph())
    fastapi_app.state.browser_factory = _fake_browser_factory
    # 실행 게이트가 참조하는 숨김 집합에 합성 id 만 넣는다(픽스처 노출 상태와 분리).
    monkeypatch.setattr(runs_mod, "_HIDDEN_AGENT_IDS", frozenset({HIDDEN_AGENT_ID}))
    yield


def test_precondition_gate_set_contains_synthetic_hidden():
    # 회귀 앵커: 게이트 대상 id 가 숨김 집합에 있어야 아래 차단 테스트가 의미 있다.
    assert HIDDEN_AGENT_ID in runs_mod._HIDDEN_AGENT_IDS


@pytest.mark.asyncio
async def test_hidden_agent_blocked_for_non_admin_403(client, make_user, make_agent, auth_as):
    """(a) 숨김 에이전트 + 비관리자 → 403(검증 전 안내)."""
    uid = await make_user("u-hidden-nonadmin", "user")
    auth_as(uid)
    await make_agent(HIDDEN_AGENT_ID, workflow_id=HIDDEN_WF, access_configured=False)
    r = await client.post("/runs/collect", json={"agentId": HIDDEN_WF})
    assert r.status_code == 403
    assert "검증 전" in r.json()["error"]


@pytest.mark.asyncio
async def test_hidden_agent_allowed_for_admin_200(client, make_user, make_agent, auth_as):
    """(b) 숨김 에이전트 + 관리자 → 통과(게이트 스모크 실행 허용)."""
    uid = await make_user("u-hidden-admin", "admin")
    auth_as(uid)
    await make_agent(HIDDEN_AGENT_ID, workflow_id=HIDDEN_WF, access_configured=False)
    r = await client.post("/runs/collect", json={"agentId": HIDDEN_WF})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_non_hidden_agent_unaffected_200(client, make_user, make_agent, auth_as):
    """(c) 숨김 목록에 없는 에이전트는 비관리자도 정상 실행(불변)."""
    uid = await make_user("u-visible", "user")
    auth_as(uid)
    await make_agent("a-visible-run", workflow_id=VISIBLE_WF, access_configured=False)
    r = await client.post("/runs/collect", json={"agentId": VISIBLE_WF})
    assert r.status_code == 200
