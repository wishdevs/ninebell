"""/auth/me 권한 평탄화 + 본인 프로필 수정(PATCH) 검증."""

from __future__ import annotations

from sqlalchemy import select

from app.core.permissions import ALL_PERMISSIONS
from app.models import User


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
    assert resp.json()["permissions"] == ["agents:read", "agents:run"]


async def test_me_unauthenticated_returns_401(client):
    # get_current_user 오버라이드 없이(쿠키 없음) 호출 → 401.
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_update_me_changes_email_only(client, sm, make_user, auth_as):
    uid = await make_user("u2", "user")
    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one()
        u.department = "개발팀"
        await s.commit()
    auth_as(uid)

    resp = await client.patch("/auth/me", json={"email": "u2@example.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "u2@example.com"
    assert data["displayName"] == "u2"
    assert data["department"] == "개발팀"

    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one()
        assert u.email == "u2@example.com"


async def test_update_me_ignores_display_name_and_department(client, sm, make_user, auth_as):
    """이름/부서는 ERP 동기화값 — PATCH /auth/me 로 보내도 무시된다."""
    uid = await make_user("u3", "user")
    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one()
        u.department = "개발팀"
        await s.commit()
    auth_as(uid)

    resp = await client.patch(
        "/auth/me",
        json={"displayName": "가짜이름", "department": "가짜부서", "email": "u3@example.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["displayName"] == "u3"
    assert data["department"] == "개발팀"

    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one()
        assert u.display_name == "u3"
        assert u.department == "개발팀"
        assert u.email == "u3@example.com"
