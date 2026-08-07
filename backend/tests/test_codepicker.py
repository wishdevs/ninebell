"""nbkit.omnisol.codepicker 공용 엔진 무결성 계약 — 브라우저 없이(2026-08-07 감사 회귀).

고정하는 계약:
  1. 검색창 미발견(PICKER_SEARCH_JS ok:false)이면 **미필터 전체 목록으로 진행하지 않고**
     하드 실패한다 — 상위 25행 창의 우연 매칭이 오선택 코드로 전표에 기록되거나(매칭 2건 이상이
     1건만 창에 들어온 경우) 허위 '일치 없음'이 되는 사고 차단.
  2. 실패 반환(_fail)은 열린 피커를 닫고 **닫힘을 확인**한다 — 안 닫힌 스테일 피커는 다음
     fill_codepicker 가 자기 팝업으로 오독한다(2026-07-24 부서팝업 동형). 미닫힘이면 원래
     실패 사유를 덮지 않고 병기한다.
  3. _open_picker 버튼 출현 폴 상한은 실시간(monotonic) — 종전 명목 24회 카운터는 delay_scale
     0.15 에서 관찰창이 6s→~0.9s 로 붕괴해 카탈로그 0건 실패가 재발했다(2026-07-10 경로).

페이크는 실물 시맨틱을 지킨다 — 버튼을 클릭해야 팝업이 열리고, 닫기/적용이 실제로 팝업 상태를
바꾼다(임의 통과 스텁이면 개폐 확인이 무의미해진다).
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import codepicker, js_lib

pytestmark = pytest.mark.asyncio

BTN = (11, 11)
APPLY = (22, 22)


class _Mouse:
    def __init__(self, page) -> None:
        self._page = page

    async def click(self, x, y):
        self._page.on_click(x, y)


class _Keyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    async def press(self, key):
        self.pressed.append(key)


class _PickerPage:
    """코드피커 실물 시맨틱 fake — 버튼 클릭으로 팝업이 열리고 닫기/적용으로 닫힌다."""

    def __init__(self, *, search_ok: bool = True, options=None, close_works: bool = True) -> None:
        self.popup_open = False
        self._search_ok = search_ok
        self._options = options or []
        self._close_works = close_works
        self.read_calls = 0
        self.waits: list[int] = []
        self.mouse = _Mouse(self)
        self.keyboard = _Keyboard()

    def on_click(self, x, y):
        if (x, y) == BTN:
            self.popup_open = True
        elif (x, y) == APPLY:
            self.popup_open = False

    async def evaluate(self, js_src, arg=None):
        if isinstance(js_src, str) and "-wrapper" in js_src:
            return {"x": BTN[0], "y": BTN[1]}
        if js_src is js_lib.PICKER_ROWCOUNT_JS:
            return len(self._options) if self.popup_open else -1
        if js_src is js_lib.PICKER_SEARCH_JS:
            return {"ok": self._search_ok}
        if js_src is js_lib.PICKER_READ_JS:
            self.read_calls += 1
            return {"rows": len(self._options), "options": self._options}
        if js_src is js_lib.PICKER_SELECT_JS:
            return {"ok": True}
        if js_src is js_lib.PICKER_APPLY_BTN_JS:
            return {"x": APPLY[0], "y": APPLY[1]}
        if js_src is js_lib.PICKER_CLOSE_JS:
            if self.popup_open and self._close_works:
                self.popup_open = False
                return True
            return False
        raise AssertionError(f"예상치 못한 evaluate: {str(js_src)[:60]}")

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


_TWO_OPTS = [
    {"i": 0, "code": "A100", "name": "가나 물산"},
    {"i": 1, "code": "B200", "name": "다라 상사"},
]


async def test_fill_codepicker_hard_fails_when_search_box_missing():
    """검색창 세팅 실패 시 미필터 목록 매칭으로 진행하지 않는다 — 하드 실패 + 피커 정리."""
    page = _PickerPage(search_ok=False, options=_TWO_OPTS)
    r = await codepicker.fill_codepicker(page, "bg_cd", "가나", "BG_CD", "BG_NM")
    assert r["ok"] is False
    assert "검색창" in r["reason"] and "가나" in r["reason"]
    assert page.read_calls == 0  # 미필터 목록을 읽고 매칭하러 가지 않는다.
    assert "Enter" not in page.keyboard.pressed  # 미적용 검색어로 재조회하지 않는다.
    assert page.popup_open is False  # 실패 정리로 피커가 닫혔다.


async def test_fill_codepicker_fail_path_closes_picker_verified():
    """실패 반환 경로가 피커를 닫고 닫힘을 확인한다(정상 닫힘이면 경고 병기 없음)."""
    page = _PickerPage(options=_TWO_OPTS)
    r = await codepicker.fill_codepicker(page, "bg_cd", "", "BG_CD", "BG_NM")
    assert r["ok"] is False and "keyword 필요" in r["reason"]
    assert page.popup_open is False
    assert "미닫힘" not in r["reason"]


async def test_fill_codepicker_fail_appends_warning_when_picker_wont_close():
    """닫기가 안 듣는 피커 — 원래 실패 사유를 덮지 않고 미닫힘 경고를 병기한다."""
    page = _PickerPage(options=_TWO_OPTS, close_works=False)
    r = await codepicker.fill_codepicker(page, "bg_cd", "", "BG_CD", "BG_NM")
    assert r["ok"] is False
    assert "keyword 필요" in r["reason"] and "미닫힘" in r["reason"]
    assert page.popup_open is True  # 실제로 안 닫혔음을 사실대로 반영.


async def test_open_picker_button_poll_cap_is_realtime_not_nominal():
    """버튼 출현 폴 상한은 실시간 — 종전 명목 상한(24회)을 넘겨 늦게 렌더되는 버튼도
    실시간 상한(6s × 배율) 안이면 잡는다(카탈로그 덤프 0건 재발 경로 차단)."""

    class _LateBtnPage(_PickerPage):
        def __init__(self) -> None:
            super().__init__(options=[{"i": 0, "code": "A100", "name": "가나 물산"}])
            self.btn_polls = 0

        async def evaluate(self, js_src, arg=None):
            if isinstance(js_src, str) and "-wrapper" in js_src:
                self.btn_polls += 1
                if self.btn_polls < 30:  # 종전 명목 상한(24회)보다 늦은 출현.
                    return None
                return {"x": BTN[0], "y": BTN[1]}
            return await super().evaluate(js_src, arg)

    page = _LateBtnPage()
    ok = await codepicker._open_picker(page, "bg_cd")
    assert ok is True, "실시간 상한이면 30번째 폴에서 버튼을 잡아야 한다"
    assert page.btn_polls >= 30
