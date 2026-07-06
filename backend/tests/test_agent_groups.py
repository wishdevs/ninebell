"""에이전트 그룹(2뎁스) — 시드 멱등성 + 직렬화 shape 테스트.

- seed_agent_groups: 그룹 upsert(멱등) + name/description/sort_order 동기화.
- seed_agents: 기존 에이전트의 group_id 를 픽스처와 동기화(0016 이전 시드 보강).
- 직렬화: 그룹 소속 에이전트는 group={id,name}, 단독 에이전트는 group=null.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Agent, AgentGroup
from app.services.agent_fixtures import AGENT_GROUP_FIXTURES
from app.services.seed import seed_all


# ── 시드 ─────────────────────────────────────────────────────────────────────
async def test_seed_agent_groups_is_idempotent(sm):
    # sm 픽스처가 이미 1회 시드함 → 한 번 더 실행해도 중복이 없어야 한다.
    async with sm() as s:
        await seed_all(s)
        await s.commit()

    async with sm() as s:
        count = (await s.execute(select(func.count()).select_from(AgentGroup))).scalar_one()
        group = await s.get(AgentGroup, "resolution")

    assert count == len(AGENT_GROUP_FIXTURES)
    assert group is not None
    assert group.name == "결의서입력"
    assert group.sort_order == 0


async def test_seed_agent_groups_syncs_fields(sm):
    # 운영에서 그룹 필드가 어긋나도 재시드가 픽스처 값으로 되돌린다.
    async with sm() as s:
        group = await s.get(AgentGroup, "resolution")
        group.name = "옛 이름"
        group.description = None
        group.sort_order = 99
        await s.commit()

    async with sm() as s:
        await seed_all(s)
        await s.commit()

    async with sm() as s:
        group = await s.get(AgentGroup, "resolution")
        fx = next(f for f in AGENT_GROUP_FIXTURES if f["id"] == "resolution")
    assert group.name == fx["name"]
    assert group.description == fx["description"]
    assert group.sort_order == fx["sort_order"]


async def test_seed_agents_backfills_group_id(sm):
    # 0016 이전에 시드된 기존 에이전트(group_id NULL)도 재시드로 그룹 소속이 보강된다.
    async with sm() as s:
        agent = await s.get(Agent, "card-chat")
        agent.group_id = None
        await s.commit()

    async with sm() as s:
        await seed_all(s)
        await s.commit()

    async with sm() as s:
        agent = await s.get(Agent, "card-chat")
    assert agent.group_id == "resolution"


# ── 직렬화 shape ─────────────────────────────────────────────────────────────
async def test_agent_serializes_group(client, make_user, auth_as):
    uid = await make_user("group-admin", "super_admin")
    auth_as(uid)

    resp = await client.get("/agents/card-chat")
    assert resp.status_code == 200
    assert resp.json()["group"] == {
        "id": "resolution",
        "name": "결의서입력",
        "description": "더존 옴니솔 결의서(GLDDOC00300) 문서군 — 카드·출장·경조금·학자금",
    }


async def test_standalone_agent_group_is_null(client, make_user, auth_as, make_agent):
    uid = await make_user("group-admin2", "super_admin")
    auth_as(uid)
    await make_agent("standalone-x", workflow_id="wf-standalone-x")

    resp = await client.get("/agents")
    assert resp.status_code == 200
    by_id = {a["id"]: a for a in resp.json()}
    assert by_id["standalone-x"]["group"] is None
    assert by_id["card-chat"]["group"]["id"] == "resolution"
    assert by_id["card-chat"]["group"]["name"] == "결의서입력"
