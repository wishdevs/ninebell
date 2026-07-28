"""아바타(사용자 패널 열기) 셀렉터 회귀 — 브라우저 없이.

⚠ 라이브 장애(2026-07-27): 아바타를 이미지 src(`img[src*=profile_circle]`)로 잡고 있었는데,
**프로필 사진을 올린 계정**은 src 가 `/download/image/<uuid>` 라 매칭이 아예 안 됐다 →
아바타 클릭 4s 타임아웃 → 패널 미개방 → `read_current_user_type` 이 '?' →
"사용자 유형 선택기를 찾을 수 없습니다"로 **사용자유형 전환 실패**(계정 '석대현').

실측 DOM(두 계정 공통): 헤더 우상단 `<a class="user-pic"><img alt="이름"></a>`.
  - 기본 아바타 계정: `<img src="/images/profile_circle.png">`
  - 사진 업로드 계정: `<img src="/download/image/47dbd625…">`
열린 패널 안에도 `div.user-pic`(48×48)이 있어 **태그(a)를 고정**해야 패널 내부를 눌러 토글로
닫는 사고가 안 난다.
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import auth, js_lib, selectors

pytestmark = pytest.mark.asyncio


async def test_avatar_selector_does_not_depend_on_image_src():
    # src 기반으로 되돌리면 사진 업로드 계정에서 다시 깨진다.
    assert "profile_circle" not in selectors.AVATAR
    assert "src" not in selectors.AVATAR
    # 패널 안 div.user-pic 과 구분되도록 앵커 태그를 고정한다.
    assert selectors.AVATAR.startswith("a.")


async def test_avatar_click_js_fallback_prefers_anchor_over_src():
    js = js_lib.AVATAR_CLICK_JS
    assert "a.user-pic" in js
    # 앵커를 먼저 찾고, 그다음에야 기본 아바타 이미지로 폴백한다.
    assert js.index("a.user-pic") < js.index("profile_circle")


class _PanelPage:
    """아바타 클릭 후에만 사용자유형 select 가 나타나는 페이지."""

    def __init__(self, *, clickable: str) -> None:
        self._clickable = clickable
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
            self._opened = True
            return None
        if js_src == js_lib.USER_TYPE_READ_JS:
            return "SCM-회계" if self._opened else "?"
        return None

    async def wait_for_timeout(self, ms):
        return None


async def test_open_user_panel_clicks_avatar_anchor_and_reads_type():
    page = _PanelPage(clickable=selectors.AVATAR)
    await auth.open_user_panel(page)
    assert page.clicked == [selectors.AVATAR]
    assert page.js_fallback == 0
    assert await auth.read_current_user_type(page) == "SCM-회계"


async def test_open_user_panel_falls_back_to_js_when_real_click_fails():
    page = _PanelPage(clickable="never-matches")
    await auth.open_user_panel(page)
    assert page.js_fallback == 1  # 실클릭 실패 → JS 폴백으로 패널을 연다.
    assert await auth.read_current_user_type(page) == "SCM-회계"


async def test_read_current_user_type_returns_question_mark_when_panel_closed():
    page = _PanelPage(clickable=selectors.AVATAR)
    # 패널을 열지 않은 상태 — 선택기가 없으므로 '?'(호출부가 UserTypeError 로 승격).
    assert await auth.read_current_user_type(page) == "?"
