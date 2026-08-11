"""app.erp.login — nbkit 래퍼 전환 후 공개 계약(authenticate/ErpAuthError) 검증.

호출부(app/routers/auth.py)가 의존하는 계약:
- ``authenticate(browser, userid, password, base)`` 시그니처와
  ``{display_name, job_title, department, email}`` 반환 형식,
- 실패 시 ``app.erp.login.ErpAuthError`` 로 잡힘.
(테스트 위치: 이 워크스트림의 신규 테스트 디렉터리가 nbkit/tests 라 여기 둔다 —
 브라우저 없이 ensure_logged_in 을 모킹해 래퍼 로직만 검증.)
"""

from __future__ import annotations

import pytest

import app.erp.login as erp_login
from nbkit.omnisol import selectors
from nbkit.omnisol.errors import AuthError, LoginPageError


class _FakeContext:
    def __init__(self) -> None:
        self.closed = False

    async def new_page(self):
        return object()  # ensure_logged_in 은 모킹되므로 page 는 불투명 토큰이면 충분

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[_FakeContext] = []
        self.viewports: list[dict | None] = []

    async def new_context(self, viewport=None):
        self.viewports.append(viewport)
        ctx = _FakeContext()
        self.contexts.append(ctx)
        return ctx


def test_erp_auth_error_is_nbkit_auth_error_alias():
    # 라우터의 `except ErpAuthError` 가 nbkit 로그인 실패(AuthError)를 그대로 잡는 근거.
    assert erp_login.ErpAuthError is AuthError


async def test_empty_credentials_raise_before_creating_context():
    browser = _FakeBrowser()
    with pytest.raises(erp_login.ErpAuthError):
        await erp_login.authenticate(browser, "", "pw", "https://erp.example.com")
    assert browser.contexts == []  # 컨텍스트 생성 전에 실패(기존 동작 유지)


async def test_authenticate_maps_profile_and_splits_job_title(monkeypatch):
    async def _fake_ensure(page, userid, password, base, **kw):
        assert (userid, password, base) == ("u1", "pw", "https://erp.example.com")
        return {"profile": {"display_name": "석대현 프로", "department": "인사/기획팀",
                            "user_types": ["회계사용자"]}}

    monkeypatch.setattr(erp_login, "ensure_logged_in", _fake_ensure)
    browser = _FakeBrowser()
    out = await erp_login.authenticate(browser, "u1", "pw", "https://erp.example.com")
    assert out == {
        "display_name": "석대현",
        "job_title": "프로",
        "department": "인사/기획팀",
        "email": None,
    }
    assert browser.viewports == [selectors.VIEWPORT]
    assert browser.contexts[0].closed  # 자격증명 비저장 — 컨텍스트 즉시 폐기


async def test_authenticate_failure_raises_erp_auth_error_and_closes_context(monkeypatch):
    # 자격증명 불일치(AuthError)는 종전대로 ErpAuthError 로 나간다(401 + 시도제한 카운트).
    async def _fake_ensure(page, userid, password, base, **kw):
        raise AuthError("아이디 또는 비밀번호가 올바르지 않습니다.")

    monkeypatch.setattr(erp_login, "ensure_logged_in", _fake_ensure)
    browser = _FakeBrowser()
    with pytest.raises(erp_login.ErpAuthError):
        await erp_login.authenticate(browser, "u1", "bad", "https://erp.example.com")
    assert browser.contexts[0].closed  # 실패 경로에서도 컨텍스트 정리


async def test_login_page_error_promotes_to_infra_error_not_erp_auth_error(monkeypatch):
    # 페이지 미로드(옴니솔 점검·SPA 지연)는 자격증명 실패가 아니다 — ErpAuthError(401 +
    # 시도제한 카운트)가 아닌 인프라성 예외로 승격돼 라우터 502 경로(except Exception)를 탄다.
    async def _fake_ensure(page, userid, password, base, **kw):
        raise LoginPageError("로그인 페이지가 로드되지 않았습니다(폼/대시보드 모두 미출현).")

    monkeypatch.setattr(erp_login, "ensure_logged_in", _fake_ensure)
    browser = _FakeBrowser()
    with pytest.raises(RuntimeError) as exc_info:
        await erp_login.authenticate(browser, "u1", "pw", "https://erp.example.com")
    assert not isinstance(exc_info.value, erp_login.ErpAuthError)  # 401/리미터 경로 미진입
    assert "ERP 접속 지연/점검" in str(exc_info.value)  # 사용자 메시지 취지 유지
    assert exc_info.value.__cause__.__class__ is LoginPageError  # 원인 체이닝 보존
    assert browser.contexts[0].closed  # 인프라 오류 경로에서도 컨텍스트 정리


def test_login_page_error_is_auth_error_subclass():
    # 기존 nbkit 소비자(에이전트 로그인 노드 등)의 `except AuthError` 동작 불변 근거.
    assert issubclass(LoginPageError, AuthError)


async def test_authenticate_profile_missing_fields_defaults(monkeypatch):
    # 프로필 추출 실패(빈 dict/None)여도 계약 형식은 유지된다(빈 값 + email None).
    async def _fake_ensure(page, userid, password, base, **kw):
        return {"profile": None}

    monkeypatch.setattr(erp_login, "ensure_logged_in", _fake_ensure)
    out = await erp_login.authenticate(_FakeBrowser(), "u1", "pw", "https://erp.example.com")
    assert out == {"display_name": "", "job_title": "", "department": "", "email": None}
