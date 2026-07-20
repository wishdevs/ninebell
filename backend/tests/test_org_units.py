"""P3-4 org_units 라우터 테스트 — 조직구분 CRUD + 에이전트 접근(agent-access).

전 엔드포인트 admin+ 게이트(require_role_min). user 롤은 403. seed_all 로 조직구분 7종·
card-chat 에이전트가 미리 있다.
"""

from __future__ import annotations

import pytest


# ── 시드 조직트리에서 id 를 동적으로 뽑는 헬퍼 ─────────────────────────────────────
# 시드가 옛 2단계 slug(hq_sales 등) 대신 경로해시 id 로 바뀌어, 테스트는 하드코딩 대신
# GET /org-units 응답에서 본부(parentId=None)·말단 팀(leaf)을 골라 쓴다.
def _roots(rows: list[dict]) -> list[dict]:
    """최상위 본부 — parentId 가 없는 행."""
    return [o for o in rows if o["parentId"] is None]


def _leaves(rows: list[dict]) -> list[dict]:
    """말단 팀 — 부모를 가지되 다른 어떤 org 의 부모도 아닌 행."""
    parent_ids = {o["parentId"] for o in rows if o["parentId"]}
    return [o for o in rows if o["parentId"] is not None and o["id"] not in parent_ids]


def _own_members(rows: list[dict]) -> list[dict]:
    """직속 인원이 있는 노드 — memberCount − sum(직속자식 memberCount) > 0(팀 + 직속인원 있는 그룹/본부)."""
    child_sum: dict[str, int] = {}
    for o in rows:
        if o["parentId"]:
            child_sum[o["parentId"]] = child_sum.get(o["parentId"], 0) + (o.get("memberCount") or 0)
    return [o for o in rows if (o.get("memberCount") or 0) - child_sum.get(o["id"], 0) > 0]


def _containers(rows: list[dict]) -> list[dict]:
    """직속 인원이 없는 순수 컨테이너(예: 경영본부 31=자식합)."""
    own = {o["id"] for o in _own_members(rows)}
    return [o for o in rows if o["id"] not in own]


async def _org_rows(client) -> list[dict]:
    """admin 인증 상태에서 GET /org-units 목록(camelCase dict)을 반환."""
    return (await client.get("/org-units")).json()


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
    rows = r.json()
    by_label = {o["label"]: o for o in rows}
    # 본부(전체깊이 ERP 시드)는 라벨로 확인 — parentId=None 인 최상위.
    assert {"경영본부", "영업본부", "임원실"} <= set(by_label)
    assert by_label["경영본부"]["parentId"] is None
    # 말단 팀(leaf)에는 parentId·costType 이 실린다.
    team = by_label["영업팀"]
    assert team["parentId"] is not None and team["costType"] is not None
    # 다단계(본부>그룹>팀): 재무자원관리그룹은 경영본부 밑 중간계층(자식을 가진다).
    grp = by_label["재무자원관리그룹"]
    assert grp["parentId"] == by_label["경영본부"]["id"]
    assert any(o["parentId"] == grp["id"] for o in rows)


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
    rows = await _org_rows(client)
    own_ids = [o["id"] for o in _own_members(rows)]  # 접근 대상 = 직속 인원 있는 노드
    container_ids = {o["id"] for o in _containers(rows)}
    r = await client.get("/agent-access")
    assert r.status_code == 200
    card = next(a for a in r.json() if a["agentId"] == "card-chat")
    # access_configured=false(시드 기본) → 전체 접근대상 + '미지정' 허용.
    assert len(card["orgUnitIds"]) == len(own_ids) + 1
    assert card["orgUnitIds"][-1] == "__none__"
    assert not (container_ids & set(card["orgUnitIds"]))  # 순수 컨테이너는 접근 대상 아님


async def test_set_agent_access_replaces_and_marks_configured(client, make_user, auth_as):
    uid = await make_user("u-admin4", "admin")
    auth_as(uid)
    leaf_a, leaf_b = (o["id"] for o in _leaves(await _org_rows(client))[:2])
    r = await client.patch("/agent-access/card-chat", json={"orgUnitIds": [leaf_a, leaf_b]})
    assert r.status_code == 200
    assert set(r.json()["orgUnitIds"]) == {leaf_a, leaf_b}
    # 이제 configured → GET 이 축소된 목록 반환.
    after = next(a for a in (await client.get("/agent-access")).json() if a["agentId"] == "card-chat")
    assert set(after["orgUnitIds"]) == {leaf_a, leaf_b}


async def test_set_agent_access_unknown_agent_404(client, make_user, auth_as):
    uid = await make_user("u-admin5", "admin")
    auth_as(uid)
    (leaf,) = (o["id"] for o in _leaves(await _org_rows(client))[:1])
    assert (
        await client.patch("/agent-access/nope", json={"orgUnitIds": [leaf]})
    ).status_code == 404


async def test_set_agent_access_all_invalid_422(client, make_user, auth_as):
    uid = await make_user("u-admin6", "admin")
    auth_as(uid)
    # 비어있지 않은데 전부 무효 id → 조용히 전체 해제 않고 422(stale 목록 방지).
    r = await client.patch("/agent-access/card-chat", json={"orgUnitIds": ["ghost1", "ghost2"]})
    assert r.status_code == 422


async def test_set_agent_access_unassigned_sentinel_roundtrip(client, make_user, auth_as):
    """'__none__' 센티널 → allow_unassigned 저장·응답/GET 재노출."""
    uid = await make_user("u-admin7", "admin")
    auth_as(uid)
    (leaf,) = (o["id"] for o in _leaves(await _org_rows(client))[:1])
    r = await client.patch(
        "/agent-access/card-chat", json={"orgUnitIds": [leaf, "__none__"]}
    )
    assert r.status_code == 200
    assert r.json()["orgUnitIds"] == [leaf, "__none__"]
    after = next(
        a for a in (await client.get("/agent-access")).json() if a["agentId"] == "card-chat"
    )
    assert after["orgUnitIds"] == [leaf, "__none__"]
    # 센티널 해제 시 allow_unassigned 도 꺼진다.
    r2 = await client.patch("/agent-access/card-chat", json={"orgUnitIds": [leaf]})
    assert r2.json()["orgUnitIds"] == [leaf]


async def test_set_agent_access_only_unassigned_is_valid(client, make_user, auth_as):
    """센티널만 있는 요청도 유효(미지정 사용자만 허용) — 422 가 아니다."""
    uid = await make_user("u-admin8", "admin")
    auth_as(uid)
    r = await client.patch("/agent-access/card-chat", json={"orgUnitIds": ["__none__"]})
    assert r.status_code == 200
    assert r.json()["orgUnitIds"] == ["__none__"]


# ── 2뎁스(본부→팀) + 비용구분 ──────────────────────────────────────────────────
async def test_create_team_under_hq_with_cost_type(client, make_user, auth_as):
    uid = await make_user("u-admin9", "admin")
    auth_as(uid)
    hq = _roots(await _org_rows(client))[0]["id"]  # 실제 시드 본부(top-level)
    r = await client.post(
        "/org-units", json={"label": "신규팀", "parentId": hq, "costType": "제조원가"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["parentId"] == hq and body["costType"] == "제조원가"


async def test_create_team_under_team_rejected(client, make_user, auth_as):
    """팀 아래에는 하위를 만들 수 없다(2뎁스 고정)."""
    uid = await make_user("u-admin10", "admin")
    auth_as(uid)
    leaf = _leaves(await _org_rows(client))[0]["id"]  # 팀(leaf) 밑에 하위 생성 시도
    r = await client.post("/org-units", json={"label": "3뎁스", "parentId": leaf})
    assert r.status_code == 422


async def test_invalid_cost_type_rejected(client, make_user, auth_as):
    uid = await make_user("u-admin11", "admin")
    auth_as(uid)
    hq = _roots(await _org_rows(client))[0]["id"]
    r = await client.post(
        "/org-units", json={"label": "x", "parentId": hq, "costType": "엉뚱"}
    )
    assert r.status_code == 422


async def test_cost_type_on_container_rejected_own_member_allowed(client, make_user, auth_as):
    """순수 컨테이너(직속 인원 0)엔 비용구분 불가 — 직속 인원 있는 노드(팀·그룹)엔 허용."""
    uid = await make_user("u-admin12", "admin")
    auth_as(uid)
    rows = await _org_rows(client)
    container = _containers(rows)[0]["id"]  # 예: 경영본부(31=자식합)
    r = await client.patch(f"/org-units/{container}", json={"costType": "판관비"})
    assert r.status_code == 422
    member = _own_members(rows)[0]["id"]  # 직속 인원 있는 노드
    r2 = await client.patch(f"/org-units/{member}", json={"costType": "제조원가"})
    assert r2.status_code == 200
    assert r2.json()["costType"] == "제조원가"
