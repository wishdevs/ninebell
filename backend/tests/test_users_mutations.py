"""P3-4 users PATCH 뮤테이션 — orgUnitId 지정/해제/검증 + status + 권한 게이트.

PATCH /users/{id} 는 users:write 권한 필요. orgUnitId 는 model_fields_set 로 '미포함=변경없음'
과 'null=해제'를 구분하고, 값 지정 시 org_units 존재를 검증(없으면 400)한다.
"""

from __future__ import annotations

import pytest


async def test_patch_requires_users_write(client, make_user, auth_as):
    target = await make_user("t-user", "user")
    actor = await make_user("u-plain", "user")  # user 롤 = users:write 없음
    auth_as(actor)
    r = await client.patch(f"/users/{target}", json={"status": "suspended"})
    assert r.status_code == 403


async def test_patch_sets_and_clears_org_unit(client, make_user, auth_as):
    target = await make_user("t-target", "user")
    admin = await make_user("u-adm", "admin")
    auth_as(admin)
    # 유효 org 지정 — 멤버는 팀(leaf)에만 배정 가능.
    r = await client.patch(f"/users/{target}", json={"orgUnitId": "hq_sales__t0"})
    assert r.status_code == 200 and r.json()["orgUnitId"] == "hq_sales__t0"
    # null 로 해제.
    r2 = await client.patch(f"/users/{target}", json={"orgUnitId": None})
    assert r2.status_code == 200 and r2.json()["orgUnitId"] is None
    # 본부(비-leaf)에는 배정 불가 → 400.
    r3 = await client.patch(f"/users/{target}", json={"orgUnitId": "hq_sales"})
    assert r3.status_code == 400


async def test_patch_unknown_org_unit_400(client, make_user, auth_as):
    target = await make_user("t-target2", "user")
    admin = await make_user("u-adm2", "admin")
    auth_as(admin)
    r = await client.patch(f"/users/{target}", json={"orgUnitId": "ghost"})
    assert r.status_code == 400


async def test_patch_org_unit_omitted_is_no_change(client, make_user, auth_as, set_user_org):
    target = await make_user("t-target3", "user")
    await set_user_org(target, "mgmt")
    admin = await make_user("u-adm3", "admin")
    auth_as(admin)
    # orgUnitId 미포함 → 기존 값 유지(status 만 변경).
    r = await client.patch(f"/users/{target}", json={"status": "suspended"})
    assert r.status_code == 200
    assert r.json()["orgUnitId"] == "mgmt"
    assert r.json()["status"] == "suspended"
