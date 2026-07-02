"""P1-C 로그인 시도 제한 + admin 비밀번호 회전 테스트.

- LoginRateLimiter 단위(주입 clock): 임계 도달→잠금, 백오프 2배, 창 만료 해제, reset, ip=None.
- /auth/login 엔드포인트: 로컬 admin 오답 5회→6회째 429+Retry-After, 잠금 우선.
- seed_local_admin: env 로 신규 생성/기본값 회전/운영변경 불변.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

import app.db as appdb
from app.core.ratelimit import LoginRateLimiter
from app.core.security import hash_password, verify_password
from app.erp.credcache import CredCache
from app.main import app as fastapi_app
from app.models import Base, User
from app.services.seed import seed_all, seed_local_admin
from sqlalchemy import select


# ── 단위: LoginRateLimiter ────────────────────────────────────────────────────
class _FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_locks_after_max_attempts_and_backoff():
    clk = _FakeClock()
    rl = LoginRateLimiter(max_attempts=3, window_s=900, lockout_base_s=30, lockout_max_s=900, clock=clk)
    assert rl.check("1.1.1.1", "admin") is None
    for _ in range(3):
        rl.record_failure("1.1.1.1", "admin")
    blocked = rl.check("1.1.1.1", "admin")
    assert blocked is not None and 1 <= blocked <= 30  # 1차 잠금 30s

    # 잠금 만료 후 다시 임계 도달 → 백오프 2배(60s).
    clk.t += 31
    assert rl.check("1.1.1.1", "admin") is None
    for _ in range(3):
        rl.record_failure("1.1.1.1", "admin")
    blocked2 = rl.check("1.1.1.1", "admin")
    assert blocked2 is not None and 31 <= blocked2 <= 60


def test_window_expiry_and_reset():
    clk = _FakeClock()
    rl = LoginRateLimiter(max_attempts=3, window_s=100, clock=clk)
    rl.record_failure("1.1.1.1", "admin")
    rl.record_failure("1.1.1.1", "admin")
    clk.t += 101  # 창 밖으로 → 카운트 prune
    assert rl.check("1.1.1.1", "admin") is None
    rl.record_failure("1.1.1.1", "admin")  # 창 리셋 후 1건뿐 → 잠금 없음
    assert rl.check("1.1.1.1", "admin") is None
    # reset 은 userid 창 제거
    rl.record_failure("1.1.1.1", "admin")
    rl.record_failure("1.1.1.1", "admin")
    rl.reset("admin")
    assert rl.check("1.1.1.1", "admin") is None


def test_ip_none_uses_user_window_only():
    rl = LoginRateLimiter(max_attempts=2, clock=_FakeClock())
    rl.record_failure(None, "admin")
    rl.record_failure(None, "admin")
    assert rl.check(None, "admin") is not None  # userid 창만으로 잠금


def test_userid_normalized():
    rl = LoginRateLimiter(max_attempts=2, clock=_FakeClock())
    rl.record_failure(None, "Admin")
    rl.record_failure(None, " admin ")
    assert rl.check(None, "ADMIN") is not None  # 대소문자·공백 정규화 동일 키


# ── 엔드포인트: /auth/login rate limit ────────────────────────────────────────
@pytest_asyncio.fixture
async def limiter_on():
    # 성공 로그인 경로가 _issue_session → cred_cache 를 쓰므로 함께 제공(lifespan 미실행 대체).
    fastapi_app.state.login_limiter = LoginRateLimiter(max_attempts=5, clock=_FakeClock())
    fastapi_app.state.cred_cache = CredCache()
    yield
    del fastapi_app.state.login_limiter


async def test_login_blocks_after_5_failures(client, limiter_on):
    for _ in range(5):
        r = await client.post("/auth/login", json={"userid": "admin", "password": "wrong"})
        assert r.status_code == 401
    r6 = await client.post("/auth/login", json={"userid": "admin", "password": "wrong"})
    assert r6.status_code == 429
    assert "Retry-After" in r6.headers
    # 잠금 중엔 올바른 비밀번호(1111)도 429(잠금 우선).
    r_correct = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert r_correct.status_code == 429


async def test_login_success_resets(client, limiter_on):
    for _ in range(4):
        await client.post("/auth/login", json={"userid": "admin", "password": "wrong"})
    ok = await client.post("/auth/login", json={"userid": "admin", "password": "1111"})
    assert ok.status_code == 200
    # 리셋 후 다시 4회 실패해도 잠금 안 됨(카운터 초기화 확인).
    for _ in range(4):
        r = await client.post("/auth/login", json={"userid": "admin", "password": "wrong"})
        assert r.status_code == 401


# ── seed: admin 비밀번호 env·회전 ─────────────────────────────────────────────
@pytest_asyncio.fixture
async def seeded_sm(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/seed.db"
    appdb.init_engine(url)
    async with appdb.get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield appdb.get_sessionmaker()
    await appdb.dispose_engine()


async def _admin(sm) -> User:
    async with sm() as s:
        return (await s.execute(select(User).where(User.omnisol_userid == "admin"))).scalar_one()


async def test_seed_admin_uses_env_password(seeded_sm, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_ADMIN_PASSWORD", "s3cret-env")
    async with seeded_sm() as s:
        await seed_all(s)
        await s.commit()
    admin = await _admin(seeded_sm)
    assert verify_password("s3cret-env", admin.password_hash)
    assert not verify_password("1111", admin.password_hash)
    get_settings.cache_clear()


async def test_seed_rotates_default_but_not_custom(seeded_sm, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    # 1) env 없이 최초 시드 → 기본 1111
    async with seeded_sm() as s:
        await seed_all(s)
        await s.commit()
    assert verify_password("1111", (await _admin(seeded_sm)).password_hash)

    # 2) env 지정 후 재시드 → 기본값이므로 회전됨
    monkeypatch.setenv("LOCAL_ADMIN_PASSWORD", "rotated-pw")
    get_settings.cache_clear()
    async with seeded_sm() as s:
        await seed_local_admin(s)
        await s.commit()
    assert verify_password("rotated-pw", (await _admin(seeded_sm)).password_hash)

    # 3) 운영자가 수동 변경(다른 해시)한 뒤 재시드 → env 와 달라도 불변
    async with seeded_sm() as s:
        admin = (await s.execute(select(User).where(User.omnisol_userid == "admin"))).scalar_one()
        admin.password_hash = hash_password("manual-op-pw")
        await s.commit()
    monkeypatch.setenv("LOCAL_ADMIN_PASSWORD", "another-env")
    get_settings.cache_clear()
    async with seeded_sm() as s:
        await seed_local_admin(s)
        await s.commit()
    assert verify_password("manual-op-pw", (await _admin(seeded_sm)).password_hash)
    get_settings.cache_clear()
