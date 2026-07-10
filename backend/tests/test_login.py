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
    fastapi_app.state.login_semaphore = asyncio.Semaphore(1)
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


async def test_login_not_blocked_by_exhausted_run_semaphore(client, monkeypatch):
    """세마포어 분리(P3-5): 실행 세마포어가 완전히 점유돼도 로그인은 login_semaphore 로 통과.

    분리 전에는 단일 세마포어를 공유해 장기 실행이 로그인을 막았다. run_semaphore 를 0 permit
    으로 소진시켜도 로그인이 200 이면 두 경로가 격리됐다는 증거."""
    async def _fake(browser, userid, password, base):
        raise AssertionError("로컬 admin 은 옴니솔 미호출")

    _wire_state(monkeypatch, _fake)
    fastapi_app.state.run_semaphore = asyncio.Semaphore(0)  # 실행 슬롯 전부 점유 상태
    try:
        resp = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
        assert resp.status_code == 200
    finally:
        del fastapi_app.state.run_semaphore


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


async def test_remember_me_extends_session_ttl(client, sm, monkeypatch):
    """'로그인 상태 유지'(remember=true) → 쿠키 Max-Age 가 remember_ttl(기본 30일)로 연장."""
    from app.config import get_settings

    async def _must_not_call(browser, userid, password, base):
        raise AssertionError("로컬 계정 로그인은 옴니솔을 호출하면 안 된다.")

    _wire_state(monkeypatch, _must_not_call)
    settings = get_settings()

    # 기본(remember 미지정) → 12h.
    r1 = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert r1.status_code == 200
    sc1 = r1.headers["set-cookie"]
    assert f"Max-Age={settings.session_ttl_seconds}" in sc1

    # remember=true → 30일.
    r2 = await client.post(
        "/auth/login", json={"userid": "admin", "password": "1111", "remember": True}
    )
    assert r2.status_code == 200
    sc2 = r2.headers["set-cookie"]
    assert f"Max-Age={settings.remember_ttl_seconds}" in sc2
    assert settings.remember_ttl_seconds > settings.session_ttl_seconds


# ---- 세션 쿠키 Domain(front·api 서브도메인 공유) ----------------------------


async def test_cookie_domain_applied_when_configured(client, monkeypatch):
    """COOKIE_DOMAIN 설정 시 Set-Cookie 에 Domain 속성이 실린다.

    운영에서 front(ninebell.hynro.com) 프록시가 api(ninebell-api.hynro.com) 발급 세션 쿠키를
    보려면 부모 도메인(.hynro.com)으로 발급해야 한다.
    """

    async def _must_not_call(browser, userid, password, base):
        raise AssertionError("로컬 계정 로그인은 옴니솔을 호출하면 안 된다.")

    _wire_state(monkeypatch, _must_not_call)
    monkeypatch.setattr(get_settings(), "cookie_domain", ".hynro.com")

    resp = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert resp.status_code == 200
    assert "Domain=.hynro.com" in resp.headers["set-cookie"]


async def test_cookie_domain_absent_by_default(client, monkeypatch):
    """기본(COOKIE_DOMAIN 미설정) → host-only. 로컬은 front·api 가 같은 localhost 라 공유된다."""

    async def _must_not_call(browser, userid, password, base):
        raise AssertionError("로컬 계정 로그인은 옴니솔을 호출하면 안 된다.")

    _wire_state(monkeypatch, _must_not_call)
    monkeypatch.setattr(get_settings(), "cookie_domain", "")

    resp = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert resp.status_code == 200
    assert "Domain=" not in resp.headers["set-cookie"]
