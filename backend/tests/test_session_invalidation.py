"""P3-3 세션 무효화 — 로그아웃/재로그인 시 JWT가 서버에서 실제로 무효화되는지.

JWT는 무상태라 get_current_user 가 CredCache 존재를 검사하지 않으면 로그아웃해도 토큰이
살아있다. 여기서는 실 로그인 쿠키로 /auth/me 를 호출해 (1) 로그아웃 후 401, (2) 재로그인이
이전 세션을 무효화(last-login-wins)함을 검증한다. CredCache 미존재 시엔 스킵(런타임엔 항상 존재).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.erp.credcache import CredCache
from app.main import app as fastapi_app


# ── 단위: CredCache.evict_user ────────────────────────────────────────────────
def test_evict_user_removes_only_that_users_entries():
    cc = CredCache()
    cc.put("jti-a1", "alice", "pw", ttl_seconds=100)
    cc.put("jti-a2", "alice", "pw", ttl_seconds=100)
    cc.put("jti-b1", "bob", "pw", ttl_seconds=100)
    removed = cc.evict_user("alice")
    assert removed == 2
    assert cc.get("jti-a1") is None
    assert cc.get("jti-a2") is None
    assert cc.get("jti-b1") is not None  # 다른 사용자 불변


# ── 엔드포인트: 로그아웃/재로그인 무효화 ────────────────────────────────────────
@pytest_asyncio.fixture
async def cred_cache_on():
    fastapi_app.state.cred_cache = CredCache()
    yield fastapi_app.state.cred_cache
    del fastapi_app.state.cred_cache


async def test_logout_invalidates_session(client, cred_cache_on):
    # 로컬 admin 실 로그인(옴니솔 우회) → 쿠키 발급 + CredCache 엔트리.
    r = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert r.status_code == 200
    # 세션 유효 — /auth/me 통과.
    assert (await client.get("/auth/me")).status_code == 200
    # 로그아웃 → jti 제거.
    assert (await client.post("/auth/logout")).status_code == 200
    # 쿠키(JWT)는 아직 클라이언트에 남아있어도 서버가 무효화 → 401.
    me2 = await client.get("/auth/me")
    assert me2.status_code == 401


async def test_evicted_jti_rejected_even_with_valid_cookie(client, cred_cache_on):
    """쿠키(JWT)가 그대로 남아있어도 CredCache 에서 jti 가 사라지면 거부 — 게이트 격리 검증.

    (로그아웃의 delete_cookie 에 의존하지 않고, CredCache 무효화만으로 401 이 되는지 확인.
     TTL 만료·재로그인 축출과 동일 경로.)"""
    r = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert r.status_code == 200
    assert (await client.get("/auth/me")).status_code == 200
    # 쿠키는 유지한 채 서버측 자격증명만 축출(로그아웃 delete_cookie 흉내 아님).
    cred_cache_on.evict_user("admin")
    # 클라이언트 쿠키(JWT)는 여전히 전송되지만 서버가 무효화 → 401.
    assert "session" in client.cookies
    assert (await client.get("/auth/me")).status_code == 401


async def test_relogin_evicts_previous_session(client, cred_cache_on):
    r1 = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert r1.status_code == 200
    # CredCache 에 admin 엔트리 1개.
    assert sum(1 for e in cred_cache_on._store.values() if e.data.get("u") == "admin") == 1
    # 재로그인 → 이전 엔트리 무효화 후 새 엔트리(여전히 1개, last-login-wins).
    r2 = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert r2.status_code == 200
    assert sum(1 for e in cred_cache_on._store.values() if e.data.get("u") == "admin") == 1
