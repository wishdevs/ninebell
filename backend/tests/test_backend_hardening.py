"""백엔드 보안·안정성 감사 수정 검증.

- 운영 부팅 가드: cookie_secure=true + 기본 auth_secret 이면 Settings 생성 실패.
- jti↔사용자 바인딩: 유효 jti 에 타인 sub 를 재서명한 토큰은 401(권한 상승 차단).
- 에러 dual-key: HTTPException 응답 body 에 detail·error 병기.
- email 형식 검증: SignupBody/AuthMeUpdate 가 잘못된 형식을 422 로 거부.
- verify_password_async: 이벤트 루프 밖(스레드) 실행 래퍼의 판정 동일성.
- 다중 워커 가드: --workers/-w/WEB_CONCURRENCY 탐지 + >1 이면 기동 거부.
- DB 풀: PG 엔진에 settings 노브가 적용되고 SQLite 경로는 불변.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import app.db as appdb
from app.config import _DEV_AUTH_SECRET, Settings
from app.core.security import create_session_token, decode_session_token, hash_password, verify_password_async
from app.erp.credcache import CredCache
from app.main import _detect_worker_count, _ensure_single_worker
from app.main import app as fastapi_app
from app.schemas.auth import AuthMeUpdate, SignupBody


# ── 1) auth_secret 운영 부팅 가드 ────────────────────────────────────────────
def test_prod_boot_rejects_default_auth_secret():
    with pytest.raises(ValidationError, match="AUTH_SECRET"):
        Settings(cookie_secure=True, auth_secret=_DEV_AUTH_SECRET)


def test_prod_boot_allows_real_auth_secret():
    s = Settings(cookie_secure=True, auth_secret="a-real-operational-secret")
    assert s.auth_secret == "a-real-operational-secret"


def test_dev_boot_allows_default_auth_secret():
    # 테스트/로컬(cookie_secure=false)은 기본 시크릿 부팅이 깨지지 않아야 한다.
    s = Settings(cookie_secure=False, auth_secret=_DEV_AUTH_SECRET)
    assert s.auth_secret == _DEV_AUTH_SECRET


# ── 2) jti↔사용자 바인딩 ────────────────────────────────────────────────────
@pytest.fixture
def cred_cache_on():
    fastapi_app.state.cred_cache = CredCache()
    yield fastapi_app.state.cred_cache
    del fastapi_app.state.cred_cache


async def test_resigned_sub_on_valid_jti_rejected(client, cred_cache_on, make_user):
    """시크릿 유출 가정: 유효한 jti(admin 세션)에 타인 sub 를 재서명해도 401 이어야 한다."""
    victim_id = await make_user("victim", "super_admin")

    r = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert r.status_code == 200
    assert (await client.get("/auth/me")).status_code == 200

    # admin 세션의 jti 를 그대로 두고 sub 만 victim 으로 바꿔 재서명(위조 토큰).
    jti = decode_session_token(client.cookies["session"])["jti"]
    forged, _ = create_session_token(str(victim_id), jti=jti)
    # 기존 쿠키(도메인 속성 다름)와의 중복을 피해 교체.
    client.cookies.delete("session")
    client.cookies.set("session", forged)

    assert (await client.get("/auth/me")).status_code == 401


async def test_legitimate_session_still_accepted(client, cred_cache_on):
    # 바인딩 검사가 정상 세션(캐시 u == 사용자 omnisol_userid)을 깨지 않는지 확인.
    r = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert r.status_code == 200
    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["omnisolUserid"] == "admin"


# ── 3) 에러 응답 dual-key ────────────────────────────────────────────────────
async def test_http_exception_body_has_detail_and_error(client):
    # 미인증 /auth/me — get_current_user 의 HTTPException 이 핸들러를 타는지.
    r = await client.get("/auth/me")
    assert r.status_code == 401
    body = r.json()
    assert body["detail"] == body["error"]
    assert "세션" in body["detail"]


async def test_login_failure_dual_key(client):
    r = await client.post("/auth/login", json={"userid": "admin", "password": "wrong"})
    assert r.status_code == 401
    body = r.json()
    assert body["detail"] == body["error"]
    assert "올바르지 않습니다" in body["detail"]


# ── 4) email 형식 검증 ──────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["not-an-email", "a@b", "a b@c.com", "@x.com", "a@.com "])
def test_signup_body_rejects_invalid_email(bad):
    with pytest.raises(ValidationError):
        SignupBody(signupToken="t", agreedTerms=True, email=bad)


@pytest.mark.parametrize("ok", [None, "", "  ", "user@example.com", "a.b+tag@sub.domain.co.kr"])
def test_signup_body_accepts_valid_or_empty_email(ok):
    body = SignupBody(signupToken="t", agreedTerms=True, email=ok)
    assert body.email == ok


def test_auth_me_update_rejects_invalid_email():
    with pytest.raises(ValidationError):
        AuthMeUpdate(email="broken@@example..com")


async def test_patch_me_invalid_email_422(client, make_user, auth_as):
    uid = await make_user("emailuser", "user")
    auth_as(uid)
    r = await client.patch("/auth/me", json={"email": "not-an-email"})
    assert r.status_code == 422


async def test_patch_me_valid_and_clear_email(client, make_user, auth_as):
    uid = await make_user("emailuser2", "user")
    auth_as(uid)
    r = await client.patch("/auth/me", json={"email": "person@example.com"})
    assert r.status_code == 200
    assert r.json()["email"] == "person@example.com"
    # 빈문자열 = 이메일 지움(기존 동작 유지).
    r2 = await client.patch("/auth/me", json={"email": ""})
    assert r2.status_code == 200
    assert r2.json()["email"] is None


# ── 5) bcrypt async 래퍼 ────────────────────────────────────────────────────
async def test_verify_password_async_matches_sync():
    h = hash_password("1111")
    assert await verify_password_async("1111", h) is True
    assert await verify_password_async("9999", h) is False
    assert await verify_password_async("1111", "not-a-bcrypt-hash") is False


# ── 6) 다중 워커 기동 가드 ──────────────────────────────────────────────────
def test_detect_worker_count_cli_and_env():
    assert _detect_worker_count(argv=["uvicorn", "--workers", "4"], env={}) == 4
    assert _detect_worker_count(argv=["uvicorn", "--workers=2"], env={}) == 2
    assert _detect_worker_count(argv=["uvicorn", "-w", "3"], env={}) == 3
    assert _detect_worker_count(argv=["uvicorn"], env={"WEB_CONCURRENCY": "5"}) == 5
    assert _detect_worker_count(argv=["uvicorn"], env={}) is None
    # CLI 가 env 보다 우선(uvicorn 규약과 동일).
    assert _detect_worker_count(argv=["uvicorn", "--workers", "1"], env={"WEB_CONCURRENCY": "8"}) == 1


def test_ensure_single_worker_rejects_multi(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(RuntimeError, match="단일 워커"):
        _ensure_single_worker()


def test_ensure_single_worker_allows_single(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    _ensure_single_worker()  # 예외 없음
    monkeypatch.delenv("WEB_CONCURRENCY")
    monkeypatch.setattr("sys.argv", ["uvicorn", "app.main:app", "--workers", "1"])
    _ensure_single_worker()  # 예외 없음


# ── 7) DB 풀 명시 설정 ──────────────────────────────────────────────────────
async def test_pg_engine_uses_settings_pool_knobs():
    from app.config import get_settings

    s = get_settings()
    # 엔진 생성은 접속하지 않으므로 실 PG 없이 풀 파라미터만 검증 가능.
    engine = appdb.init_engine("postgresql+asyncpg://u:p@localhost:1/x")
    try:
        pool = engine.sync_engine.pool
        assert pool.size() == s.db_pool_size
        assert pool._max_overflow == s.db_max_overflow
    finally:
        await appdb.dispose_engine()


async def test_sqlite_engine_path_unchanged(tmp_path):
    engine = appdb.init_engine(f"sqlite+aiosqlite:///{tmp_path}/pool.db")
    try:
        # SQLite 경로는 풀 노브 미적용 — 엔진 생성과 접속이 그대로 성공해야 한다.
        async with engine.connect():
            pass
    finally:
        await appdb.dispose_engine()
