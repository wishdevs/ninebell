"""로그인 흐름 검증(CONTRACT_V2 A) — authenticate 모킹(실제 브라우저 미사용).

- 로컬 계정(admin/1111): bcrypt 로컬 검증, 옴니솔 미호출. 오답 401.
- 신규 옴니솔 유저: signupRequired 반환(세션 미발급).
- 기존 옴니솔 유저: 기존처럼 즉시 세션 발급.
- 실패: access_log(failed) + 401.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

import app.erp.login as erp_login
from app.config import get_settings
from app.erp.credcache import CredCache
from app.main import app as fastapi_app
from app.models import AccessLog, User
from app.services.signup_cache import SignupCache


async def _fake_authenticate(browser, userid, password, base):
    return {"display_name": "보스", "department": "경영지원", "email": None}


def _wire_state(monkeypatch, fake):
    monkeypatch.setattr(erp_login, "authenticate", fake)
    fastapi_app.state.erp_semaphore = asyncio.Semaphore(1)
    fastapi_app.state.erp_browser = object()  # 모킹된 authenticate 가 사용하지 않음
    fastapi_app.state.cred_cache = CredCache()
    fastapi_app.state.signup_cache = SignupCache()


# ---- 로컬 계정(admin/1111) --------------------------------------------------


async def test_local_admin_login_succeeds_without_omnisol(client, sm, monkeypatch):
    async def _must_not_call(browser, userid, password, base):
        raise AssertionError("로컬 계정 로그인은 옴니솔을 호출하면 안 된다.")

    _wire_state(monkeypatch, _must_not_call)

    resp = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "session" in resp.cookies  # 세션 쿠키 발급

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "admin"))).scalar_one()
        assert u.role.code == "super_admin"
        assert u.last_login_at is not None


async def test_local_admin_wrong_password_401_and_logs_failed(client, sm, monkeypatch):
    _wire_state(monkeypatch, _fake_authenticate)

    resp = await client.post("/auth/login", json={"userid": "admin", "password": "9999"})
    assert resp.status_code == 401
    assert "session" not in resp.cookies

    async with sm() as s:
        rows = (
            await s.execute(select(AccessLog).where(AccessLog.omnisol_userid == "admin"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "failed"


# ---- 신규 옴니솔 유저 → 회원가입 유도 ---------------------------------------


async def test_new_omnisol_user_returns_signup_required(client, sm, monkeypatch):
    _wire_state(monkeypatch, _fake_authenticate)

    resp = await client.post("/auth/login", json={"userid": "newbie", "password": "pw"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["signupRequired"] is True
    assert data["signupToken"]
    assert data["prefill"] == {"displayName": "보스", "department": "경영지원"}
    assert "session" not in resp.cookies  # 세션 미발급

    # 유저는 아직 생성되지 않는다.
    async with sm() as s:
        assert (
            await s.execute(select(User).where(User.omnisol_userid == "newbie"))
        ).scalar_one_or_none() is None
        # access_log(success) 는 user_id 없이 기록.
        rows = (
            await s.execute(select(AccessLog).where(AccessLog.omnisol_userid == "newbie"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "success"
        assert rows[0].user_id is None


# ---- 기존 옴니솔 유저 → 즉시 세션 ------------------------------------------


async def test_existing_omnisol_user_login_succeeds(client, sm, make_user, monkeypatch):
    await make_user("carol", "user")  # password_hash 없음 = 옴니솔 계정
    _wire_state(monkeypatch, _fake_authenticate)

    resp = await client.post("/auth/login", json={"userid": "carol", "password": "pw"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "session" in resp.cookies

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "carol"))).scalar_one()
        assert u.last_login_at is not None
        rows = (
            await s.execute(select(AccessLog).where(AccessLog.omnisol_userid == "carol"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "success"
        assert rows[0].user_id == u.id


async def test_failed_omnisol_login_records_failed_and_401(client, sm, monkeypatch):
    async def _fail(browser, userid, password, base):
        raise erp_login.ErpAuthError("아이디 또는 비밀번호가 올바르지 않습니다.")

    _wire_state(monkeypatch, _fail)

    resp = await client.post("/auth/login", json={"userid": "bad", "password": "x"})
    assert resp.status_code == 401

    async with sm() as s:
        rows = (
            await s.execute(select(AccessLog).where(AccessLog.omnisol_userid == "bad"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "failed"
        assert rows[0].user_id is None

    get_settings.cache_clear()
