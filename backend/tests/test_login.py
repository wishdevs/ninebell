"""로그인 흐름 검증 — authenticate 모킹(실제 브라우저 미사용).

최초 로그인 시 super_admin 부여(env), 일반 사용자 기본 user, 실패 시 access_log + 401.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

import app.erp.login as erp_login
from app.config import get_settings
from app.erp.credcache import CredCache
from app.main import app as fastapi_app
from app.models import AccessLog, User


async def _fake_authenticate(browser, userid, password, base):
    return {"display_name": "보스", "department": "경영지원", "email": None}


def _wire_state(monkeypatch, fake):
    monkeypatch.setattr(erp_login, "authenticate", fake)
    fastapi_app.state.erp_semaphore = asyncio.Semaphore(1)
    fastapi_app.state.erp_browser = object()  # 모킹된 authenticate 가 사용하지 않음
    fastapi_app.state.cred_cache = CredCache()


async def test_first_login_assigns_super_admin_from_env(client, sm, monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_OMNISOL_IDS", "boss01")
    get_settings.cache_clear()
    _wire_state(monkeypatch, _fake_authenticate)

    resp = await client.post("/auth/login", json={"userid": "boss01", "password": "pw"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "session" in resp.cookies  # httpOnly 세션 쿠키 발급

    async with sm() as s:
        u = (
            await s.execute(select(User).where(User.omnisol_userid == "boss01"))
        ).scalar_one()
        assert u.role.code == "super_admin"
        assert u.display_name == "보스"

    get_settings.cache_clear()


async def test_first_login_defaults_to_user_role(client, sm, monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_OMNISOL_IDS", "boss01")
    get_settings.cache_clear()
    _wire_state(monkeypatch, _fake_authenticate)

    resp = await client.post("/auth/login", json={"userid": "alice", "password": "pw"})
    assert resp.status_code == 200

    async with sm() as s:
        u = (
            await s.execute(select(User).where(User.omnisol_userid == "alice"))
        ).scalar_one()
        assert u.role.code == "user"

    get_settings.cache_clear()


async def test_failed_login_records_access_log_and_401(client, sm, monkeypatch):
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


async def test_successful_login_records_access_log(client, sm, monkeypatch):
    get_settings.cache_clear()
    _wire_state(monkeypatch, _fake_authenticate)

    resp = await client.post("/auth/login", json={"userid": "carol", "password": "pw"})
    assert resp.status_code == 200

    async with sm() as s:
        rows = (
            await s.execute(select(AccessLog).where(AccessLog.omnisol_userid == "carol"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "success"
        assert rows[0].user_id is not None
