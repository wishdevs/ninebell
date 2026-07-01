"""/auth/me 권한 평탄화 검증."""

from __future__ import annotations

from app.core.permissions import ALL_PERMISSIONS


async def test_me_flattens_admin_permissions(client, make_user, auth_as):
    uid = await make_user("admin1", "admin")
    auth_as(uid)
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "admin"
    assert data["omnisolUserid"] == "admin1"
    assert set(data["permissions"]) == set(ALL_PERMISSIONS)


async def test_me_user_role_minimal_permissions(client, make_user, auth_as):
    uid = await make_user("u1", "user")
    auth_as(uid)
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["permissions"] == ["agents:read"]


async def test_me_unauthenticated_returns_401(client):
    # get_current_user 오버라이드 없이(쿠키 없음) 호출 → 401.
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
