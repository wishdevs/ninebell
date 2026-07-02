"""P3-4 org_units 라우터 테스트 — 조직구분 CRUD + 에이전트 접근(agent-access).

전 엔드포인트 admin+ 게이트(require_role_min). user 롤은 403. seed_all 로 조직구분 7종·
card-chat 에이전트가 미리 있다.
"""

from __future__ import annotations

import pytest


# ── 권한 게이트 ────────────────────────────────────────────────────────────────
async def test_list_org_units_requires_admin(client, make_user, auth_as):
    uid = await make_user("u-user", "user")
    auth_as(uid)
    assert (await client.get("/org-units")).status_code == 403


async def test_list_org_units_admin_sees_seeded(client, make_user, auth_as):
    uid = await make_user("u-admin", "admin")
    auth_as(uid)
    r = await client.get("/org-units")
    assert r.status_code == 200
    ids = {o["id"] for o in r.json()}
    assert {"exec", "sales", "mgmt"} <= ids  # seed_org_units 7종 일부


# ── CRUD 라이프사이클 ──────────────────────────────────────────────────────────
async def test_org_unit_crud_lifecycle(client, make_user, auth_as):
    uid = await make_user("u-admin2", "admin")
    auth_as(uid)
    # create
    r = await client.post("/org-units", json={"label": "신규본부"})
    assert r.status_code == 201
    oid = r.json()["id"]
    # update
    r2 = await client.patch(f"/org-units/{oid}", json={"label": "개명본부"})
    assert r2.status_code == 200 and r2.json()["label"] == "개명본부"
    # delete
    assert (await client.delete(f"/org-units/{oid}")).status_code == 204
    # update 없는 대상 → 404
    assert (await client.patch(f"/org-units/{oid}", json={"label": "x"})).status_code == 404


# ── 에이전트 접근(agent-access) ────────────────────────────────────────────────
async def test_agent_access_unconfigured_returns_all(client, make_user, auth_as):
    uid = await make_user("u-admin3", "admin")
    auth_as(uid)
    r = await client.get("/agent-access")
    assert r.status_code == 200
    card = next(a for a in r.json() if a["agentId"] == "card-chat")
    # access_configured=false(시드 기본) → 전체 조직구분 허용.
    assert len(card["orgUnitIds"]) == 7


async def test_set_agent_access_replaces_and_marks_configured(client, make_user, auth_as):
    uid = await make_user("u-admin4", "admin")
    auth_as(uid)
    r = await client.patch("/agent-access/card-chat", json={"orgUnitIds": ["sales", "mgmt"]})
    assert r.status_code == 200
    assert set(r.json()["orgUnitIds"]) == {"sales", "mgmt"}
    # 이제 configured → GET 이 축소된 목록 반환.
    after = next(a for a in (await client.get("/agent-access")).json() if a["agentId"] == "card-chat")
    assert set(after["orgUnitIds"]) == {"sales", "mgmt"}


async def test_set_agent_access_unknown_agent_404(client, make_user, auth_as):
    uid = await make_user("u-admin5", "admin")
    auth_as(uid)
    assert (
        await client.patch("/agent-access/nope", json={"orgUnitIds": ["sales"]})
    ).status_code == 404


async def test_set_agent_access_all_invalid_422(client, make_user, auth_as):
    uid = await make_user("u-admin6", "admin")
    auth_as(uid)
    # 비어있지 않은데 전부 무효 id → 조용히 전체 해제 않고 422(stale 목록 방지).
    r = await client.patch("/agent-access/card-chat", json={"orgUnitIds": ["ghost1", "ghost2"]})
    assert r.status_code == 422
