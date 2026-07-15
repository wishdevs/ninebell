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
from app.models import OrgUnit, User
from app.services.signup_cache import SignupCache


async def _fake_authenticate(browser, userid, password, base):
    return {"display_name": "홍길동", "department": "개발팀", "email": None}


def _wire_state(monkeypatch):
    monkeypatch.setattr(erp_login, "authenticate", _fake_authenticate)
    fastapi_app.state.login_semaphore = asyncio.Semaphore(1)
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


async def test_signup_name_and_department_from_erp_ignore_body(client, sm, monkeypatch):
    """이름·부서는 ERP 인증값(pending)을 권위값으로 — 클라가 다른 값을 보내도 무시."""
    _wire_state(monkeypatch)
    # ERP 프로필: 이름=홍길동, 부서=개발팀
    token = fastapi_app.state.signup_cache.put("newbie", "pw", "홍길동", "개발팀")

    resp = await client.post(
        "/auth/signup",
        json={
            "signupToken": token,
            "displayName": "위조이름",  # 클라 조작 — 무시돼야 한다.
            "department": "위조팀",  # 클라 조작(조직구분 자동배정 키) — 무시돼야 한다.
            "agreedTerms": True,
        },
    )
    assert resp.status_code == 200

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "newbie"))).scalar_one()
        assert u.display_name == "홍길동"  # 클라 '위조이름'이 아니라 ERP 프로필값
        assert u.department == "개발팀"  # 클라 '위조팀'이 아니라 ERP 프로필값


async def test_signup_assigns_org_unit_from_department(client, sm, monkeypatch):
    """가입 시 부서(=조직구분)를 org_units 에 매칭해 org_unit_id 자동 배정 — '미지정' 방지."""
    _wire_state(monkeypatch)
    # 조직구분: 본부X ▸ 개발팀. 가입 부서 '개발팀'이 이 팀에 매칭돼야 한다.
    async with sm() as s:
        s.add_all(
            [
                OrgUnit(id="hq_x", label="본부X", parent_id=None, sort_order=0),
                OrgUnit(id="hq_x__t0", label="개발팀", parent_id="hq_x", cost_type="판관비", sort_order=0),
            ]
        )
        await s.commit()
    token = fastapi_app.state.signup_cache.put("newbie", "pw", "홍길동", "개발팀")

    resp = await client.post(
        "/auth/signup",
        json={
            "signupToken": token,
            "displayName": "홍길동",
            "department": "개발팀",
            "agreedTerms": True,
        },
    )
    assert resp.status_code == 200

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "newbie"))).scalar_one()
        assert u.org_unit_id == "hq_x__t0"  # 부서 → 팀 매칭


async def test_signup_succeeds_without_email(client, sm, monkeypatch):
    _wire_state(monkeypatch)
    token = _seed_pending("noemail")

    # email 키를 아예 생략(선택 입력).
    resp = await client.post(
        "/auth/signup",
        json={
            "signupToken": token,
            "displayName": "홍길동",
            "department": "개발팀",
            "agreedTerms": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "session" in resp.cookies

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "noemail"))).scalar_one()
        assert u.email is None
        assert u.role.code == "user"


async def test_signup_normalizes_empty_email_to_none(client, sm, monkeypatch):
    _wire_state(monkeypatch)
    token = _seed_pending("blankemail")

    resp = await client.post(
        "/auth/signup",
        json={
            "signupToken": token,
            "displayName": "홍길동",
            "department": "개발팀",
            "email": "",
            "agreedTerms": True,
        },
    )
    assert resp.status_code == 200

    async with sm() as s:
        u = (await s.execute(select(User).where(User.omnisol_userid == "blankemail"))).scalar_one()
        assert u.email is None


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
