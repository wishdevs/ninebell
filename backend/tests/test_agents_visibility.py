"""에이전트 조직접근 가시성 테스트 — GET /agents 목록 필터 + GET /agents/{id} 404.

실행 게이트(runs.py)와 동일 규칙: access_configured=True 에이전트는 user 롤에게
소속 조직구분(또는 미지정 허용)일 때만 보인다. admin+ 는 전체.
"""

from __future__ import annotations

import pytest


async def _list_ids(client) -> set[str]:
    r = await client.get("/agents")
    assert r.status_code == 200
    return {a["id"] for a in r.json()}


@pytest.mark.asyncio
async def test_unconfigured_agent_visible_to_all(client, make_user, make_agent, auth_as):
    uid = await make_user("v-open", "user")
    auth_as(uid)
    await make_agent("va-open", workflow_id="v-wf1", access_configured=False)
    assert "va-open" in await _list_ids(client)


@pytest.mark.asyncio
async def test_configured_agent_hidden_from_other_org(
    client, make_user, make_agent, set_user_org, auth_as
):
    """허용 목록에 없는 조직구분 소속 user 에게는 목록에서 숨고 상세도 404."""
    uid = await make_user("v-wrongorg", "user")
    await set_user_org(uid, "mgmt")  # 허용은 sales 뿐
    auth_as(uid)
    await make_agent(
        "va-gated", workflow_id="v-wf2", access_configured=True, allowed_org_units=("sales",)
    )
    assert "va-gated" not in await _list_ids(client)
    assert (await client.get("/agents/va-gated")).status_code == 404


@pytest.mark.asyncio
async def test_configured_agent_visible_to_allowed_org(
    client, make_user, make_agent, set_user_org, auth_as
):
    uid = await make_user("v-okorg", "user")
    await set_user_org(uid, "sales")
    auth_as(uid)
    await make_agent(
        "va-ok", workflow_id="v-wf3", access_configured=True, allowed_org_units=("sales",)
    )
    assert "va-ok" in await _list_ids(client)
    assert (await client.get("/agents/va-ok")).status_code == 200


@pytest.mark.asyncio
async def test_configured_agent_hidden_from_unassigned_unless_allowed(
    client, make_user, make_agent, auth_as
):
    """org_unit 미지정 user: allow_unassigned=False 면 숨고, True 면 보인다."""
    uid = await make_user("v-noorg", "user")
    auth_as(uid)
    await make_agent(
        "va-none-off", workflow_id="v-wf4", access_configured=True, allowed_org_units=("sales",)
    )
    await make_agent(
        "va-none-on",
        workflow_id="v-wf5",
        access_configured=True,
        allowed_org_units=("sales",),
        allow_unassigned=True,
    )
    ids = await _list_ids(client)
    assert "va-none-off" not in ids
    assert "va-none-on" in ids
    assert (await client.get("/agents/va-none-off")).status_code == 404
    assert (await client.get("/agents/va-none-on")).status_code == 200


@pytest.mark.asyncio
async def test_admin_sees_all_agents(client, make_user, make_agent, auth_as):
    uid = await make_user("v-admin", "admin")
    auth_as(uid)
    await make_agent(
        "va-admin", workflow_id="v-wf6", access_configured=True, allowed_org_units=("sales",)
    )
    assert "va-admin" in await _list_ids(client)
    assert (await client.get("/agents/va-admin")).status_code == 200
