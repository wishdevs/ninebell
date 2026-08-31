"""에이전트 **그룹** 접근관리(2026-08-31) — API(/agent-group-access) + 가시성/실행 게이트.

규칙(에이전트 접근과 대칭 + AND 결합):
  (1) 그룹 access_configured=false = 그룹 층 전체 허용(에이전트 규칙만 적용).
  (2) 그룹이 설정되면 조직구분이 그룹 allowlist 에 있어야 그 그룹의 에이전트가 보인다/실행된다.
  (3) 최종 = 그룹 AND 에이전트 — 그룹 통과 + 에이전트 차단이면 여전히 차단.
  (4) admin+ 는 두 층 모두 우회(목록·실행).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.live.registry import register_workflow
from app.main import app as fastapi_app
from app.models import Agent, AgentGroup, AgentGroupOrgAccess


class _FakeGraph:
    async def ainvoke(self, state: dict) -> dict:
        ev = state["events"]
        await ev.put({"step": "s", "status": "done"})
        return {"result": "ok"}


class _FakeBrowser:
    async def new_page(self):
        return None

    async def close(self):
        return None


async def _fake_browser_factory():
    return _FakeBrowser()


@pytest.fixture(autouse=True)
def _wire_workflow():
    register_workflow("grp-wf", lambda: _FakeGraph())
    fastapi_app.state.browser_factory = _fake_browser_factory
    yield


async def _make_group(sm, gid: str, **cols) -> None:
    async with sm() as s:
        s.add(AgentGroup(id=gid, name=gid, sort_order=99, **cols))
        await s.commit()


async def _assign_group(sm, agent_id: str, gid: str) -> None:
    async with sm() as s:
        a = (await s.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
        a.group_id = gid
        await s.commit()


async def _set_group_access(sm, gid: str, org_ids: tuple[str, ...], *, allow_unassigned=False):
    async with sm() as s:
        g = (await s.execute(select(AgentGroup).where(AgentGroup.id == gid))).scalar_one()
        g.access_configured = True
        g.allow_unassigned = allow_unassigned
        for oid in org_ids:
            s.add(AgentGroupOrgAccess(group_id=gid, org_unit_id=oid))
        await s.commit()


# ── API /agent-group-access ───────────────────────────────────────────────────
async def test_group_access_requires_admin(client, make_user, auth_as):
    uid = await make_user("g-user", "user")
    auth_as(uid)
    assert (await client.get("/agent-group-access")).status_code == 403


async def test_group_access_unconfigured_returns_all(client, make_user, auth_as):
    """미설정 그룹(시드 resolution 등)은 전체 조직 + '__none__'(끝) — 에이전트 GET 과 대칭."""
    uid = await make_user("g-admin", "admin")
    auth_as(uid)
    r = await client.get("/agent-group-access")
    assert r.status_code == 200
    rows = {g["groupId"]: g for g in r.json()}
    assert {"resolution", "voucher", "purchase"} <= set(rows)
    reso = rows["resolution"]
    assert reso["groupName"] and reso["orgUnitIds"][-1] == "__none__"
    assert len(reso["orgUnitIds"]) > 1  # 조직 노드들 + 센티널


async def test_group_access_patch_roundtrip_and_stale_422(client, make_user, auth_as):
    uid = await make_user("g-admin2", "admin")
    auth_as(uid)
    orgs = (await client.get("/org-units")).json()
    # 직속 인원이 있는 노드 하나 선택(test_org_units._own_members 와 동일 판별).
    child_sum: dict[str, int] = {}
    for o in orgs:
        if o["parentId"]:
            child_sum[o["parentId"]] = child_sum.get(o["parentId"], 0) + (o.get("memberCount") or 0)
    own = [o for o in orgs if (o.get("memberCount") or 0) - child_sum.get(o["id"], 0) > 0]
    team_id = own[0]["id"]

    r = await client.patch("/agent-group-access/resolution", json={"orgUnitIds": [team_id]})
    assert r.status_code == 200
    assert r.json() == {"groupId": "resolution", "orgUnitIds": [team_id]}
    # GET 재조회 — 설정 후에는 명시 목록만.
    rows = {g["groupId"]: g for g in (await client.get("/agent-group-access")).json()}
    assert rows["resolution"]["orgUnitIds"] == [team_id]
    # 센티널 왕복.
    r2 = await client.patch(
        "/agent-group-access/resolution", json={"orgUnitIds": [team_id, "__none__"]}
    )
    assert r2.json()["orgUnitIds"] == [team_id, "__none__"]
    # 전부 무효(stale) = 422 — 조용한 전체 해제 금지.
    r3 = await client.patch("/agent-group-access/resolution", json={"orgUnitIds": ["ghost-1"]})
    assert r3.status_code == 422
    # 없는 그룹 404.
    assert (
        await client.patch("/agent-group-access/no-such", json={"orgUnitIds": []})
    ).status_code == 404


# ── 가시성(GET /agents, /agents/{id}) ─────────────────────────────────────────
async def test_group_blocks_agent_listing_and_detail(
    client, sm, make_user, make_agent, set_user_org, auth_as
):
    """그룹이 다른 조직만 허용하면, 에이전트가 미설정(전체 허용)이어도 안 보인다(AND)."""
    await make_agent("ga-1", workflow_id="grp-wf", access_configured=False)
    await _make_group(sm, "g-vis")
    await _assign_group(sm, "ga-1", "g-vis")
    await _set_group_access(sm, "g-vis", ("sales",))

    uid = await make_user("g-mgmt", "user")
    await set_user_org(uid, "mgmt")
    auth_as(uid)
    ids = [a["id"] for a in (await client.get("/agents")).json()]
    assert "ga-1" not in ids
    assert (await client.get("/agents/ga-1")).status_code == 404

    uid2 = await make_user("g-sales", "user")
    await set_user_org(uid2, "sales")
    auth_as(uid2)
    ids2 = [a["id"] for a in (await client.get("/agents")).json()]
    assert "ga-1" in ids2
    assert (await client.get("/agents/ga-1")).status_code == 200


async def test_group_and_agent_are_anded(client, sm, make_user, make_agent, set_user_org, auth_as):
    """그룹 통과 + 에이전트 차단 = 차단(둘 다 통과해야 보인다)."""
    await make_agent(
        "ga-2", workflow_id="grp-wf", access_configured=True, allowed_org_units=("mgmt",)
    )
    await _make_group(sm, "g-and")
    await _assign_group(sm, "ga-2", "g-and")
    await _set_group_access(sm, "g-and", ("sales", "mgmt"))

    uid = await make_user("g-sales2", "user")
    await set_user_org(uid, "sales")  # 그룹은 허용, 에이전트는 mgmt 만
    auth_as(uid)
    assert "ga-2" not in [a["id"] for a in (await client.get("/agents")).json()]

    uid2 = await make_user("g-mgmt2", "user")
    await set_user_org(uid2, "mgmt")  # 둘 다 허용
    auth_as(uid2)
    assert "ga-2" in [a["id"] for a in (await client.get("/agents")).json()]


async def test_unconfigured_group_keeps_agent_rule(
    client, sm, make_user, make_agent, set_user_org, auth_as
):
    """그룹 미설정 = 그룹 층 무시 — 종전 에이전트 규칙 그대로(회귀 방지)."""
    await make_agent(
        "ga-3", workflow_id="grp-wf", access_configured=True, allowed_org_units=("sales",)
    )
    await _make_group(sm, "g-open")
    await _assign_group(sm, "ga-3", "g-open")

    uid = await make_user("g-sales3", "user")
    await set_user_org(uid, "sales")
    auth_as(uid)
    assert "ga-3" in [a["id"] for a in (await client.get("/agents")).json()]


# ── 실행 게이트(POST /runs/collect) ───────────────────────────────────────────
async def test_run_gate_blocked_by_group_403_and_admin_bypass(
    client, sm, make_user, make_agent, set_user_org, auth_as
):
    await make_agent("ga-run", workflow_id="grp-wf", access_configured=False)
    await _make_group(sm, "g-run")
    await _assign_group(sm, "ga-run", "g-run")
    await _set_group_access(sm, "g-run", ("sales",))

    uid = await make_user("g-runner", "user")
    await set_user_org(uid, "mgmt")
    auth_as(uid)
    r = await client.post("/runs/collect", json={"agentId": "grp-wf"})
    assert r.status_code == 403
    assert "그룹" in r.json().get("detail", r.json().get("error", ""))

    uid2 = await make_user("g-runner-ok", "user")
    await set_user_org(uid2, "sales")
    auth_as(uid2)
    assert (await client.post("/runs/collect", json={"agentId": "grp-wf"})).status_code == 200

    admin = await make_user("g-admin-run", "admin")
    auth_as(admin)
    assert (await client.post("/runs/collect", json={"agentId": "grp-wf"})).status_code == 200


async def test_run_gate_group_unassigned_user(client, sm, make_user, make_agent, auth_as):
    """조직 미지정 사용자 — 그룹 allow_unassigned 로만 통과."""
    await make_agent("ga-none", workflow_id="grp-wf", access_configured=False)
    await _make_group(sm, "g-none")
    await _assign_group(sm, "ga-none", "g-none")
    await _set_group_access(sm, "g-none", ("sales",))

    uid = await make_user("g-noorg", "user")
    auth_as(uid)
    assert (await client.post("/runs/collect", json={"agentId": "grp-wf"})).status_code == 403

    async with sm() as s:
        g = (await s.execute(select(AgentGroup).where(AgentGroup.id == "g-none"))).scalar_one()
        g.allow_unassigned = True
        await s.commit()
    assert (await client.post("/runs/collect", json={"agentId": "grp-wf"})).status_code == 200
