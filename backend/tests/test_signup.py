"""회원가입 흐름 검증(CONTRACT_V2 A) — POST /auth/signup.

- 유효 토큰 + agreedTerms → 유저 생성 + 세션 발급 + 약관 동의 시각/이메일 저장.
- SUPER_ADMIN_OMNISOL_IDS 에 속한 userid → super_admin 롤.
- agreedTerms 미동의 → 400. 유효하지 않은/만료 토큰 → 400.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

import app.erp.login as erp_login
from app.config import get_settings
from app.erp.credcache import CredCache
from app.main import app as fastapi_app
from app.models import User
from app.services.signup_cache import SignupCache


async def _fake_authenticate(browser, userid, password, base):
    return {"display_name": "홍길동", "department": "개발팀", "email": None}


def _wire_state(monkeypatch):
    monkeypatch.setattr(erp_login, "authenticate", _fake_authenticate)
    fastapi_app.state.erp_semaphore = asyncio.Semaphore(1)
    fastapi_app.state.erp_browser = object()
    fastapi_app.state.cred_cache = CredCache()
    fastapi_app.state.signup_cache = SignupCache()


def _seed_pending(userid: str = "newbie", password: str = "pw") -> str:
    """signup_cache 에 pending 을 직접 심고 토큰 반환."""
    return fastapi_app.state.signup_cache.put(userid, password, "홍길동", "개발팀")


async def test_signup_creates_user_and_issues_session(client, sm, monkeypatch):
    _wire_state(monkeypatch)
    token = _seed_pending("newbie")

    resp = await client.post(
        "/auth/signup",
        json={
            "signupToken": token,
            "displayName": "홍길동",
            "department": "개발팀",
            "email": "hong@example.com",
            "agreedTerms": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "session" in resp.cookies

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "newbie"))).scalar_one()
        assert u.role.code == "user"
        assert u.email == "hong@example.com"
        assert u.agreed_terms_at is not None
        assert u.last_login_at is not None
        assert u.password_hash is None  # 옴니솔 계정은 로컬 해시 없음

    # 토큰은 소비되어 재사용 불가.
    assert fastapi_app.state.signup_cache.get(token) is None


async def test_signup_assigns_super_admin_from_env(client, sm, monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_OMNISOL_IDS", "boss01")
    get_settings.cache_clear()
    _wire_state(monkeypatch)
    token = _seed_pending("boss01")

    resp = await client.post(
        "/auth/signup",
        json={
            "signupToken": token,
            "displayName": "보스",
            "department": "경영지원",
            "email": "boss@example.com",
            "agreedTerms": True,
        },
    )
    assert resp.status_code == 200

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "boss01"))).scalar_one()
        assert u.role.code == "super_admin"

    get_settings.cache_clear()


async def test_signup_rejects_when_terms_not_agreed(client, sm, monkeypatch):
    _wire_state(monkeypatch)
    token = _seed_pending("newbie")

    resp = await client.post(
        "/auth/signup",
        json={
            "signupToken": token,
            "displayName": "홍길동",
            "department": "개발팀",
            "email": "hong@example.com",
            "agreedTerms": False,
        },
    )
    assert resp.status_code == 400
    assert "session" not in resp.cookies

    async with sm() as s:
        assert (
            await s.execute(select(User).where(User.omnisol_userid == "newbie"))
        ).scalar_one_or_none() is None


async def test_signup_rejects_invalid_token(client, sm, monkeypatch):
    _wire_state(monkeypatch)

    resp = await client.post(
        "/auth/signup",
        json={
            "signupToken": "does-not-exist",
            "displayName": "홍길동",
            "department": "개발팀",
            "email": "hong@example.com",
            "agreedTerms": True,
        },
    )
    assert resp.status_code == 400
    assert "session" not in resp.cookies


async def test_login_then_signup_end_to_end(client, sm, monkeypatch):
    _wire_state(monkeypatch)

    login = await client.post("/auth/login", json={"userid": "e2euser", "password": "pw"})
    assert login.status_code == 200
    token = login.json()["signupToken"]

    signup = await client.post(
        "/auth/signup",
        json={
            "signupToken": token,
            "displayName": "홍길동",
            "department": "개발팀",
            "email": "e2e@example.com",
            "agreedTerms": True,
        },
    )
    assert signup.status_code == 200
    assert signup.json() == {"ok": True}
    assert "session" in signup.cookies

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "e2euser"))).scalar_one()
        assert u.email == "e2e@example.com"
        assert u.role.code == "user"
