"""권한 게이트 검증 — require_permission 403/200."""

from __future__ import annotations


async def test_users_list_forbidden_for_user_role(client, make_user, auth_as):
    uid = await make_user("alice", "user")
    auth_as(uid)
    resp = await client.get("/users")
    assert resp.status_code == 403


async def test_users_list_allowed_for_admin(client, make_user, auth_as):
    uid = await make_user("bob", "admin")
    auth_as(uid)
    resp = await client.get("/users")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_agents_read_allowed_for_user_role(client, make_user, auth_as):
    uid = await make_user("alice", "user")
    auth_as(uid)
    resp = await client.get("/agents")
    assert resp.status_code == 200
    # 픽스처 개수와 동기 — 카드(실동작) + 결의서입력 더미 4개(출장 2·경조금·학자금).
    from app.services.agent_fixtures import AGENT_FIXTURES

    assert len(resp.json()) == len(AGENT_FIXTURES)


async def test_agent_detail_includes_flowgraph(client, make_user, auth_as):
    uid = await make_user("alice", "user")
    auth_as(uid)
    resp = await client.get("/agents/card-chat")
    assert resp.status_code == 200
    data = resp.json()
    assert "flowGraph" in data
    assert data["intervention"]["kind"] == "chat"
    # 단계 id 는 저장 key 로 직렬화된다(실제 card-collect 그래프의 첫 노드 = login).
    assert data["steps"][0]["id"] == "login"


async def test_logs_forbidden_for_user_allowed_for_super_admin(client, make_user, auth_as):
    uid = await make_user("alice", "user")
    auth_as(uid)
    assert (await client.get("/logs")).status_code == 403

    sid = await make_user("root", "super_admin")
    auth_as(sid)
    assert (await client.get("/logs")).status_code == 200
