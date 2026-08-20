"""에이전트별 세부설정 테스트 — 선언 스키마·실효값·admin PATCH·런 파라미터 주입.

- effective_settings: 저장값 없음=스키마 기본값, 부분 저장=오버레이(미지 키 무시).
- GET /agents: 스키마 있는 에이전트(corporate-card)만 settings/settingsSchema 포함.
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
    assert effective_settings("corporate-card", None) == {"acct_cutoff_day": 9}


def test_effective_settings_overlays_stored_and_ignores_unknown():
    # 저장값이 기본값을 덮고, 스키마에 없는 키(legacy_key)는 무시된다.
    stored = {"acct_cutoff_day": 4, "legacy_key": "x"}
    assert effective_settings("corporate-card", stored) == {"acct_cutoff_day": 4}


def test_effective_settings_empty_for_schemaless_agent():
    assert effective_settings("demo", {"acct_cutoff_day": 4}) == {}


# ── 메뉴 항목(menu_items — voucher-by-type, 2026-08-20 유형별 병합) ─────────────
def test_effective_settings_menu_items_defaults():
    from app.services.agent_settings import DEFAULT_MENU_ITEMS

    eff = effective_settings("voucher-by-type", None)
    assert eff == {"menu_items": DEFAULT_MENU_ITEMS}
    assert [m["id"] for m in eff["menu_items"]] == ["sales-entry", "sales-cancel", "export-cost"]
    assert [m["defaultSelected"] for m in eff["menu_items"]] == [True, True, False]


def test_effective_settings_menu_items_stored_overrides():
    stored = {"menu_items": [{"id": "custom", "label": "커스텀메뉴", "defaultSelected": True}]}
    eff = effective_settings("voucher-by-type", stored)
    assert eff["menu_items"] == [{"id": "custom", "label": "커스텀메뉴", "defaultSelected": True}]


def test_effective_settings_menu_items_invalid_stored_falls_back():
    from app.services.agent_settings import DEFAULT_MENU_ITEMS

    # 저장값이 깨졌으면(빈 목록 등) 기본 3종으로 폴백 — 실행 경로가 죽지 않게.
    assert effective_settings("voucher-by-type", {"menu_items": []})["menu_items"] == DEFAULT_MENU_ITEMS


def test_validate_menu_items_normalizes_missing_default_selected():
    from app.services.agent_settings import validate_settings

    out = validate_settings(
        "voucher-by-type", {"menu_items": [{"id": "a", "label": "메뉴A"}]}
    )
    assert out == {"menu_items": [{"id": "a", "label": "메뉴A", "defaultSelected": False}]}


@pytest.mark.parametrize(
    "bad",
    [
        [],  # 최소 1개.
        [{"id": "a", "label": "메뉴"}] * 21,  # 최대 20개.
        [{"id": "a", "label": "메뉴"}, {"id": "a", "label": "메뉴2"}],  # id 중복.
        [{"id": "", "label": "메뉴"}],  # id 필수.
        [{"id": "a", "label": ""}],  # label 필수.
        [{"id": "a", "label": "메뉴", "defaultSelected": 1}],  # bool 아님.
        "매출등록",  # 목록 아님.
    ],
)
def test_validate_menu_items_rejects_bad_input(bad):
    from app.services.agent_settings import validate_settings

    with pytest.raises(ValueError):
        validate_settings("voucher-by-type", {"menu_items": bad})


def test_validate_settings_unknown_key_rejected_for_menu_agent():
    from app.services.agent_settings import validate_settings

    with pytest.raises(ValueError):
        validate_settings("voucher-by-type", {"acct_cutoff_day": 4})


@pytest.mark.asyncio
async def test_get_agent_includes_menu_items_settings(client, make_user, auth_as):
    """GET /agents/voucher-by-type 직렬화에 settings.menu_items(기본 3종) + 빈 스키마가 포함된다
    (스키마를 []로 선언해 settings 포함을 트리거 — 프론트 실행 전 폼의 기본 선택 소스)."""
    uid = await make_user("s-menu-reader", "admin")
    auth_as(uid)
    r = await client.get("/agents/voucher-by-type")
    assert r.status_code == 200
    body = r.json()
    assert body["settingsSchema"] == []
    assert [m["label"] for m in body["settings"]["menu_items"]] == [
        "매출등록",
        "매출취소",
        "수출비용입력[나인벨]",
    ]


@pytest.mark.asyncio
async def test_patch_menu_items_admin_ok_and_reflected(client, make_user, auth_as):
    uid = await make_user("s-menu-admin", "admin")
    auth_as(uid)
    items = [
        {"id": "sales-entry", "label": "매출등록", "defaultSelected": True},
        {"id": "custom", "label": "신규메뉴", "defaultSelected": False},
    ]
    r = await client.patch(
        "/agents/voucher-by-type/settings", json={"settings": {"menu_items": items}}
    )
    assert r.status_code == 200
    assert r.json()["settings"]["menu_items"] == items
    r2 = await client.get("/agents/voucher-by-type")
    assert r2.json()["settings"]["menu_items"] == items


@pytest.mark.asyncio
async def test_patch_menu_items_invalid_400(client, make_user, auth_as):
    uid = await make_user("s-menu-bad", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/voucher-by-type/settings", json={"settings": {"menu_items": []}}
    )
    assert r.status_code == 400
    assert "메뉴 항목" in r.json()["detail"]


# ── GET 직렬화(settings/settingsSchema 포함 여부) ─────────────────────────────
@pytest.mark.asyncio
async def test_get_agents_includes_settings_for_card_chat(client, make_user, auth_as):
    uid = await make_user("s-reader", "admin")
    auth_as(uid)
    r = await client.get("/agents/corporate-card")
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
        "/agents/corporate-card/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 200
    assert r.json()["settings"] == {"acct_cutoff_day": 4}
    # 재조회에서도 저장값이 유지된다.
    r2 = await client.get("/agents/corporate-card")
    assert r2.json()["settings"] == {"acct_cutoff_day": 4}


@pytest.mark.asyncio
async def test_patch_settings_user_forbidden_403(client, make_user, auth_as):
    uid = await make_user("s-user", "user")
    auth_as(uid)
    r = await client.patch(
        "/agents/corporate-card/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 29, "4"])
async def test_patch_settings_invalid_value_400(client, make_user, auth_as, bad):
    """범위 밖(0, 29)·타입 위반(문자열)은 400 + 한국어 메시지."""
    uid = await make_user(f"s-bad-{bad}", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/corporate-card/settings", json={"settings": {"acct_cutoff_day": bad}}
    )
    assert r.status_code == 400
    assert "회계시점 결정일" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_settings_unknown_key_400(client, make_user, auth_as):
    uid = await make_user("s-unk", "admin")
    auth_as(uid)
    r = await client.patch("/agents/corporate-card/settings", json={"settings": {"nope": 1}})
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
    """corporate-card 을 캡처용 가짜 워크플로우로 배선하고 params 캡처 리스트를 돌려준다."""
    captured: list[dict] = []
    register_workflow("settings-wf", lambda: _CaptureGraph(captured))
    fastapi_app.state.browser_factory = _fake_browser_factory

    async def _wire():
        from app.models import Agent

        async with sm() as s:
            a = (await s.execute(select(Agent).where(Agent.id == "corporate-card"))).scalar_one()
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
        "/agents/corporate-card/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert ok.status_code == 200
    r = await client.post(
        "/runs/collect",
        json={"agentId": "settings-wf", "params": {"acct_cutoff_day": 3}},
    )
    assert r.status_code == 200
    assert captured and captured[0]["acct_cutoff_day"] == 4  # 서버 저장값 승리(조작 무시)
