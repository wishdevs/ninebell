"""에이전트별 세부설정 테스트 — 선언 스키마·실효값·admin PATCH·런 파라미터 주입.

- effective_settings: 저장값 없음=스키마 기본값, 부분 저장=오버레이(미지 키 무시).
- GET /agents: 스키마 있는 에이전트(card-chat)만 settings/settingsSchema 포함.
- PATCH /agents/{id}/settings: admin 200(값 반영), user 403, 범위 밖·미지 키·스키마 없음 400,
  없는 에이전트 404.
- POST /runs/collect: 실효 설정이 params 로 평탄화 주입되고 body.params 가 우선한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.live.registry import register_workflow
from app.main import app as fastapi_app
from app.services.agent_settings import effective_settings


# ── effective_settings(순수 함수) ────────────────────────────────────────────
def test_effective_settings_defaults_when_no_stored():
    assert effective_settings("card-chat", None) == {"acct_cutoff_day": 9}


def test_effective_settings_overlays_stored_and_ignores_unknown():
    # 저장값이 기본값을 덮고, 스키마에 없는 키(legacy_key)는 무시된다.
    stored = {"acct_cutoff_day": 4, "legacy_key": "x"}
    assert effective_settings("card-chat", stored) == {"acct_cutoff_day": 4}


def test_effective_settings_empty_for_schemaless_agent():
    assert effective_settings("demo", {"acct_cutoff_day": 4}) == {}


# ── GET 직렬화(settings/settingsSchema 포함 여부) ─────────────────────────────
@pytest.mark.asyncio
async def test_get_agents_includes_settings_for_card_chat(client, make_user, auth_as):
    uid = await make_user("s-reader", "admin")
    auth_as(uid)
    r = await client.get("/agents/card-chat")
    assert r.status_code == 200
    body = r.json()
    assert body["settings"] == {"acct_cutoff_day": 9}  # 저장값 없음 → 스키마 기본값.
    schema = body["settingsSchema"]
    assert [s["key"] for s in schema] == ["acct_cutoff_day"]
    assert schema[0]["label"] == "회계시점 결정일"
    assert schema[0]["type"] == "number"
    assert (schema[0]["default"], schema[0]["min"], schema[0]["max"]) == (9, 1, 28)


@pytest.mark.asyncio
async def test_get_agents_omits_settings_for_schemaless_agent(
    client, make_user, make_agent, auth_as
):
    uid = await make_user("s-reader2", "admin")
    auth_as(uid)
    await make_agent("s-plain", workflow_id="s-wf-plain")
    r = await client.get("/agents/s-plain")
    assert r.status_code == 200
    assert "settings" not in r.json()
    assert "settingsSchema" not in r.json()


# ── PATCH /agents/{id}/settings ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_patch_settings_admin_ok_and_reflected(client, make_user, auth_as):
    uid = await make_user("s-admin", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/card-chat/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 200
    assert r.json()["settings"] == {"acct_cutoff_day": 4}
    # 재조회에서도 저장값이 유지된다.
    r2 = await client.get("/agents/card-chat")
    assert r2.json()["settings"] == {"acct_cutoff_day": 4}


@pytest.mark.asyncio
async def test_patch_settings_user_forbidden_403(client, make_user, auth_as):
    uid = await make_user("s-user", "user")
    auth_as(uid)
    r = await client.patch(
        "/agents/card-chat/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 29, "4"])
async def test_patch_settings_invalid_value_400(client, make_user, auth_as, bad):
    """범위 밖(0, 29)·타입 위반(문자열)은 400 + 한국어 메시지."""
    uid = await make_user(f"s-bad-{bad}", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/card-chat/settings", json={"settings": {"acct_cutoff_day": bad}}
    )
    assert r.status_code == 400
    assert "회계시점 결정일" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_settings_unknown_key_400(client, make_user, auth_as):
    uid = await make_user("s-unk", "admin")
    auth_as(uid)
    r = await client.patch("/agents/card-chat/settings", json={"settings": {"nope": 1}})
    assert r.status_code == 400
    assert "알 수 없는 설정" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_settings_schemaless_agent_400(client, make_user, make_agent, auth_as):
    uid = await make_user("s-nos", "admin")
    auth_as(uid)
    await make_agent("s-noschema", workflow_id="s-wf-nos")
    r = await client.patch(
        "/agents/s-noschema/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 400
    assert "설정 항목이 없습니다" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_settings_missing_agent_404(client, make_user, auth_as):
    uid = await make_user("s-404", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/s-ghost/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 404


# ── 런 파라미터 주입(runs.collect → state['params']) ─────────────────────────
class _CaptureGraph:
    """state['params'] 를 캡처하는 가짜 그래프 — 설정 평탄화 주입 검증용."""

    def __init__(self, sink: list):
        self._sink = sink

    async def ainvoke(self, state: dict) -> dict:
        self._sink.append(dict(state.get("params") or {}))
        await state["events"].put({"step": "s", "status": "done"})
        return {"result": "ok"}


class _FakeBrowser:
    async def new_page(self):
        return None

    async def close(self):
        return None


async def _fake_browser_factory():
    return _FakeBrowser()


@pytest.fixture
def capture_run_params(sm):
    """card-chat 을 캡처용 가짜 워크플로우로 배선하고 params 캡처 리스트를 돌려준다."""
    captured: list[dict] = []
    register_workflow("settings-wf", lambda: _CaptureGraph(captured))
    fastapi_app.state.browser_factory = _fake_browser_factory

    async def _wire():
        from app.models import Agent

        async with sm() as s:
            a = (await s.execute(select(Agent).where(Agent.id == "card-chat"))).scalar_one()
            a.workflow_id = "settings-wf"
            await s.commit()

    return _wire, captured


@pytest.mark.asyncio
async def test_run_params_include_effective_settings(
    client, make_user, auth_as, capture_run_params
):
    """설정 미저장 시 스키마 기본값(9)이 params 로 평탄화 주입된다."""
    wire, captured = capture_run_params
    await wire()
    uid = await make_user("s-run", "admin")
    auth_as(uid)
    r = await client.post("/runs/collect", json={"agentId": "settings-wf"})
    assert r.status_code == 200
    assert captured and captured[0]["acct_cutoff_day"] == 9


@pytest.mark.asyncio
async def test_run_params_body_cannot_override_settings(
    client, make_user, auth_as, capture_run_params
):
    """리뷰 HIGH — 저장된 관리자 설정(4)이 승리하고, body.params 의 같은 스키마 키(3)는 무시된다.

    (이전 규약: body.params 우선 → 사용자가 관리자 설정을 덮어 권한상승. 보안 수정으로 서버 권위.)
    """
    wire, captured = capture_run_params
    await wire()
    uid = await make_user("s-run2", "admin")
    auth_as(uid)
    ok = await client.patch(
        "/agents/card-chat/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert ok.status_code == 200
    r = await client.post(
        "/runs/collect",
        json={"agentId": "settings-wf", "params": {"acct_cutoff_day": 3}},
    )
    assert r.status_code == 200
    assert captured and captured[0]["acct_cutoff_day"] == 4  # 서버 저장값 승리(조작 무시)
