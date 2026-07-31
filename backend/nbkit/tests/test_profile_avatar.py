"""read_profile 아바타 클릭 경로 회귀 — 브라우저 없이.

⚠ 라이브 장애(2026-07-27): 아바타를 이미지 src(`img[src*=profile_circle]`)로 잡으면
프로필 사진 업로드 계정(src=/download/image/<uuid>)에서 매칭이 아예 안 된다.
selectors.AVATAR(`a.user-pic`)가 단일 소스이며, read_profile 은 auth.open_user_panel
을 재사용해 아바타 클릭 경로를 한 곳으로 통합한다.
"""

from __future__ import annotations

import inspect

from nbkit.omnisol import js_lib, profile, selectors


class _ProfilePage:
    """아바타 클릭 후에만 사용자 패널(유형 select + 부서)이 나타나는 페이지."""

    def __init__(self, *, clickable: str, js_fallback_works: bool = True) -> None:
        self._clickable = clickable
        self._js_fallback_works = js_fallback_works
        self.clicked: list[str] = []
        self.js_fallback = 0
        self._opened = False

    async def click(self, selector: str, timeout: int | None = None) -> None:
        if selector != self._clickable:
            raise TimeoutError(f"Timeout: waiting for locator({selector!r})")
        self.clicked.append(selector)
        self._opened = True

    async def evaluate(self, js_src: str, arg=None):
        if js_src == js_lib.AVATAR_CLICK_JS:
            self.js_fallback += 1
            if not self._js_fallback_works:
                raise RuntimeError("evaluate 실패(컨텍스트 파괴)")
            self._opened = True
            return None
        if js_src == js_lib.USER_TYPE_READ_JS:
            return "회계사용자" if self._opened else "?"
        if js_src == js_lib.PROFILE_JS:
            if not self._opened:
                return {"display_name": "", "department": "", "user_types": []}
            return {
                "display_name": "석대현 프로",
                "department": "인사/기획팀",
                "user_types": ["회계사용자", "인사사용자(예외)"],
            }
        return None

    async def wait_for_timeout(self, ms):
        return None


def test_read_profile_source_has_no_src_based_avatar_selector():
    # src 기반 셀렉터로 되돌리면 사진 업로드 계정에서 다시 깨진다(2026-07-27 장애 재발 방지).
    src = inspect.getsource(profile)
    assert "img[src*=profile_circle]" not in src


async def test_read_profile_clicks_avatar_anchor():
    page = _ProfilePage(clickable=selectors.AVATAR)
    out = await profile.read_profile(page)
    assert page.clicked == [selectors.AVATAR]
    assert page.js_fallback == 0
    assert out["display_name"] == "석대현 프로"
    assert out["department"] == "인사/기획팀"
    assert out["user_types"] == ["회계사용자", "인사사용자(예외)"]


async def test_read_profile_falls_back_to_js_when_real_click_fails():
    page = _ProfilePage(clickable="never-matches")
    out = await profile.read_profile(page)
    assert page.js_fallback >= 1  # 실클릭 실패 → JS 폴백으로 패널을 연다.
    assert out["department"] == "인사/기획팀"


async def test_read_profile_returns_empty_values_when_panel_never_opens():
    # 실클릭·JS 폴백 모두 실패해도 예외 없이 빈 값(계약: 로그인은 userid 권위로 진행 가능).
    page = _ProfilePage(clickable="never-matches", js_fallback_works=False)
    out = await profile.read_profile(page)
    assert out == {"display_name": "", "department": "", "user_types": []}
