"""사용자유형 전환 재설계(2026-08-01) — 유형 추가에 견디는 옵션-목록 기반 해석 계약.

라이브 실측(e2e/user_type_selector_probe.py)이 확정한 사실을 회귀로 고정한다:
  * 옵션 라벨 원문 3개 — `회계사용자(예외)` / `인사사용자(예외)` / **`SCM-구매`**(접미사
    '사용자' 없음, 하이픈 포함). 로그인 직후 기본 선택 = `SCM-구매`. 유형은 계속 추가된다.
  * H1 — 리더가 `.k-dropdown` 을 `/사용자/` 텍스트로 스캔해, 현재 표시가 `SCM-구매` 면
    드롭다운 자체를 못 찾아 1단계에서 즉시 실패했다. → select(#ch_group) 기준 위젯 역참조로 대체.
  * H0 — `ensure_logged_in`→`read_profile` 이 사용자 패널을 **연 채로** 남기는데,
    `switch_user_type` 첫 줄의 `open_user_panel()` 이 아바타를 또 눌러(토글) **닫아버려**
    attempt 1 을 낭비했다. → 이미 열려 있으면 클릭하지 않는다.
  * li 텍스트에는 인덱스 접미사가 붙는다(`'SCM-구매 3'`) — 라벨 매칭은 이를 흡수해야 한다.

핵심 계약: **하드코딩된 유형 목록이 없다.** 별칭은 ERP 가 실제로 주는 옵션 목록과 대조해
해석하고, 후보가 2개 이상이면 임의 선택하지 않고 모호성 오류로 실패한다.
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import auth, js_lib, latency, selectors
from nbkit.omnisol.errors import UserTypeError

_SELECTOR_PRESENT_JS = "(s) => !!document.querySelector(s)"

# 라이브 실측 옵션 원문(2026-08-01) — 기본 선택은 인덱스 2(`SCM-구매`).
LIVE_OPTIONS = ["회계사용자(예외)", "인사사용자(예외)", "SCM-구매"]

_DROPDOWN_XY = (10, 10)
_APPLY_XY = (30, 30)


def _option_xy(index: int) -> tuple[int, int]:
    return (20, 100 + index * 25)


class _Mouse:
    def __init__(self, page: "_UtPage") -> None:
        self._p = page

    async def click(self, x, y):
        self._p.clicks.append((x, y))
        self._p.on_click(x, y)


class _UtPage:
    """사용자유형 패널 FakePage — 실측 DOM 동작(토글 아바타·kendo 표시·인덱스 접미사 li)을 모사.

    JS 는 실행하지 않으므로 리더 4종의 **의미**만 재현한다. li 라벨 매칭은 UT_OPTION_BOX_JS 의
    규칙(완전일치 → 접두+인덱스접미사 → 유일 포함)을 파이썬으로 같이 구현해, auth 가 넘기는
    라벨이 실제로 유일하게 짚히는지까지 검증한다.
    """

    def __init__(self, options: list[str], selected: int, *, panel_open: bool = False) -> None:
        self.options = list(options)
        self.selected = selected  # 커밋된(변경적용된) 선택
        self.pending = selected  # 위젯 표시상의 선택
        self.panel_open = panel_open
        self.dropdown_open = False
        self.avatar_clicks = 0
        self.clicks: list[tuple[int, int]] = []
        self.marker = False
        self.reloaded = False
        self.clock_ms = 0.0
        self.mouse = _Mouse(self)

    # ── 시계(가짜) — monotonic 상한 폴링이 실시간 낭비 없이 진행되게 ──────────────
    def install_clock(self, monkeypatch) -> None:
        monkeypatch.setattr("nbkit.omnisol.auth.time.monotonic", lambda: self.clock_ms / 1_000)

    async def wait_for_timeout(self, ms):
        self.clock_ms += ms

    # ── 실클릭 ────────────────────────────────────────────────────────────────
    def on_click(self, x, y) -> None:
        if (x, y) == _DROPDOWN_XY:
            self.dropdown_open = True
            return
        if (x, y) == _APPLY_XY:
            self.selected = self.pending
            self.dropdown_open = False
            self.panel_open = False  # 변경적용은 reload — 패널이 닫힌 새 document.
            self.marker = False
            self.reloaded = True
            return
        for i in range(len(self.options)):
            if (x, y) == _option_xy(i):
                self.pending = i
                self.dropdown_open = False
                return

    async def click(self, selector: str, timeout: int | None = None) -> None:
        if selector != selectors.AVATAR:
            raise TimeoutError(f"Timeout: waiting for locator({selector!r})")
        self.avatar_clicks += 1
        self.panel_open = not self.panel_open  # ⚠ 아바타는 토글(H0 의 원인).

    # ── li 텍스트: 실측대로 인덱스 접미사가 붙는다('SCM-구매 3') ─────────────────
    def _li_texts(self) -> list[str]:
        return [f"{o} {i + 1}" for i, o in enumerate(self.options)]

    def _option_box(self, label: str):
        if not self.dropdown_open:
            return None
        want = " ".join(str(label or "").split())
        if not want:
            return None
        texts = self._li_texts()
        hits = [i for i, t in enumerate(texts) if t == want]
        if len(hits) != 1:
            hits = [
                i
                for i, t in enumerate(texts)
                if t.startswith(want) and t[len(want) :].strip(" 0123456789") == ""
            ]
        if len(hits) != 1:
            hits = [i for i, t in enumerate(texts) if want in t]
        if len(hits) != 1:
            return None
        x, y = _option_xy(hits[0])
        return {"x": x, "y": y}

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.USER_PANEL_OPEN_JS:
            return self.panel_open
        if js_src == js_lib.AVATAR_CLICK_JS:
            self.panel_open = not self.panel_open
            return None
        if js_src == js_lib.USER_TYPE_READ_JS:
            return self.options[self.selected] if self.panel_open else "?"
        if js_src == js_lib.USER_TYPE_OPTIONS_JS:
            if not self.panel_open:
                return None
            return {
                "selectId": "ch_group",
                "selectedIndex": self.selected,
                "options": list(self.options),
            }
        if js_src == js_lib.UT_DROPDOWN_BOX_JS:
            if not self.panel_open:
                return None
            return {"x": _DROPDOWN_XY[0], "y": _DROPDOWN_XY[1]}
        if js_src == js_lib.UT_OPTION_BOX_JS:
            return self._option_box(arg)
        if js_src == js_lib.UT_DISPLAY_JS:
            return self.options[self.pending] if self.panel_open else ""
        if js_src == js_lib.UT_APPLY_BOX_JS:
            if not self.panel_open:
                return None
            return {"x": _APPLY_XY[0], "y": _APPLY_XY[1]}
        if "__nbUtApplyMark = true" in js_src:
            self.marker = True
            return True
        if "__nbUtApplyMark === true" in js_src:
            return self.marker
        if js_src == _SELECTOR_PRESENT_JS and arg == selectors.AVATAR:
            return True  # 아바타는 항상 렌더(reload 후 재출현 즉시).
        if js_src == js_lib.NOTICE_POPUP_BOXES_JS:
            return None  # 공지 없음.
        return None


@pytest.fixture(autouse=True)
def _reset_latency():
    latency.reset()
    yield
    latency.reset()


# ── 별칭 → 실라벨 해석 규칙(단위) ────────────────────────────────────────────────
def test_resolve_prefers_exact_then_prefix_then_contains():
    # 접두일치: '회계' → '회계사용자(예외)'(유일).
    assert auth.resolve_user_type_label(LIVE_OPTIONS, "회계") == "회계사용자(예외)"
    # 완전일치가 접두/포함보다 우선 — 'SCM-구매' 는 그대로.
    assert auth.resolve_user_type_label(LIVE_OPTIONS, "SCM-구매") == "SCM-구매"
    # 접두일치: 'SCM' → 'SCM-구매'. 접미사 '사용자' 가정이 사라졌음을 보여준다.
    assert auth.resolve_user_type_label(LIVE_OPTIONS, "SCM") == "SCM-구매"
    # 포함일치(접두 실패 시) — '구매' 는 'SCM-구매' 안에만 있다.
    assert auth.resolve_user_type_label(LIVE_OPTIONS, "구매") == "SCM-구매"
    # 공백 표기 흔들림 흡수(정규화 = 공백 제거).
    assert auth.resolve_user_type_label(LIVE_OPTIONS, "SCM - 구매") == "SCM-구매"


def test_resolve_ambiguous_alias_fails_with_candidates():
    """③ 후보 2개면 임의 선택 금지 — 후보 목록을 노출하며 명확히 실패."""
    options = ["회계사용자(예외)", "회계-정산사용자", "인사사용자(예외)"]
    with pytest.raises(UserTypeError) as ei:
        auth.resolve_user_type_label(options, "회계")
    msg = str(ei.value)
    assert "모호" in msg
    assert "회계사용자(예외)" in msg and "회계-정산사용자" in msg


def test_resolve_unknown_target_exposes_real_options():
    """④ 미존재 target — 실제 옵션 목록을 그대로 노출(새 유형을 로그만 보고 알 수 있게)."""
    with pytest.raises(UserTypeError) as ei:
        auth.resolve_user_type_label(LIVE_OPTIONS, "총무")
    msg = str(ei.value)
    for label in LIVE_OPTIONS:
        assert label in msg


def test_resolve_treats_regex_metacharacters_literally():
    """⑤ 라벨의 정규식 메타문자는 **문자 그대로** — 종전 new RegExp(target+'사용자') 는
    '회계(A).B+' 를 패턴으로 해석해 '회계AXBB사용자' 를 잘못 짚었을 것이다."""
    options = ["회계(A).B+사용자", "회계AXBB사용자"]
    assert auth.resolve_user_type_label(options, "회계(A).B+") == "회계(A).B+사용자"


def test_option_box_js_has_no_regex_injection():
    """정규식 문자열 삽입 폐기의 구조적 고정 — 라벨을 패턴으로 만들지 않는다."""
    assert "new RegExp" not in js_lib.UT_OPTION_BOX_JS
    assert "사용자" not in js_lib.UT_OPTION_BOX_JS  # 접미사 가정 제거.


def test_ut_readers_do_not_scan_for_user_suffix():
    """H1 회귀 방지 — 드롭다운/표시 리더가 `/사용자/` 텍스트 스캔에 의존하지 않는다."""
    for src in (js_lib.UT_DROPDOWN_BOX_JS, js_lib.UT_DISPLAY_JS):
        assert "kendoDropDownList" in src  # 위젯 역참조가 1순위.
        assert "ch_group" in src  # select 탐색 1순위는 실측 확정 id.


# ── open_user_panel idempotent(H0) ──────────────────────────────────────────────
async def test_open_user_panel_does_not_close_already_open_panel():
    """⑥ 이미 열린 패널(read_profile 이 남긴 상태)을 아바타 재클릭으로 닫지 않는다."""
    page = _UtPage(LIVE_OPTIONS, selected=2, panel_open=True)
    await auth.open_user_panel(page)
    assert page.avatar_clicks == 0
    assert page.panel_open is True


async def test_open_user_panel_clicks_when_panel_closed():
    """닫혀 있으면 종전대로 아바타를 실클릭해 연다."""
    page = _UtPage(LIVE_OPTIONS, selected=2, panel_open=False)
    await auth.open_user_panel(page)
    assert page.avatar_clicks == 1
    assert page.panel_open is True


# ── 전체 전환 경로 ──────────────────────────────────────────────────────────────
async def test_switch_from_scm_to_accounting(monkeypatch):
    """① 현재=SCM-구매(로그인 직후 기본) → '회계' 전환 성공 — H1+H0 동시 회귀."""
    page = _UtPage(LIVE_OPTIONS, selected=2, panel_open=True)
    page.install_clock(monkeypatch)
    await auth.switch_user_type(page, "회계")
    assert page.options[page.selected] == "회계사용자(예외)"
    assert page.avatar_clicks == 1  # 시작 시 열린 패널 유지 + reload 후 1회 재오픈만.
    assert _APPLY_XY in page.clicks  # 변경적용까지 실클릭.


async def test_switch_to_new_type_by_alias(monkeypatch):
    """② 현재=회계 → 별칭 'SCM' 전환 성공 — 신규 유형이 코드 수정 없이 대상이 된다."""
    page = _UtPage(LIVE_OPTIONS, selected=0, panel_open=False)
    page.install_clock(monkeypatch)
    await auth.switch_user_type(page, "SCM")
    assert page.options[page.selected] == "SCM-구매"


async def test_switch_noop_when_already_target(monkeypatch):
    """이미 해당 유형이면 전환하지 않는다(동등 비교 — 접두 관계 라벨 오판 방지)."""
    page = _UtPage(["회계", "회계-정산"], selected=1, panel_open=True)
    page.install_clock(monkeypatch)
    await auth.switch_user_type(page, "회계")
    # '회계' in '회계-정산' 이라고 조기 반환하면 안 된다 — 실제로 전환해야 한다.
    assert page.options[page.selected] == "회계"
    assert _APPLY_XY in page.clicks

    page2 = _UtPage(["회계", "회계-정산"], selected=0, panel_open=True)
    page2.install_clock(monkeypatch)
    await auth.switch_user_type(page2, "회계")
    assert page2.clicks == []  # 이미 맞으므로 아무 것도 누르지 않는다.


async def test_switch_with_regex_metacharacter_labels(monkeypatch):
    """⑤ 메타문자 라벨로도 정확히 그 항목을 짚어 전환한다."""
    page = _UtPage(["회계(A).B+사용자", "회계AXBB사용자", "SCM-구매"], selected=2, panel_open=True)
    page.install_clock(monkeypatch)
    await auth.switch_user_type(page, "회계(A).B+")
    assert page.options[page.selected] == "회계(A).B+사용자"


async def test_switch_ambiguous_alias_raises_before_any_click(monkeypatch):
    """③ 모호하면 클릭 자체를 하지 않고 후보와 함께 실패한다."""
    page = _UtPage(["회계사용자(예외)", "회계-정산사용자", "SCM-구매"], selected=2, panel_open=True)
    page.install_clock(monkeypatch)
    with pytest.raises(UserTypeError) as ei:
        await auth.switch_user_type(page, "회계")
    assert "모호" in str(ei.value)
    assert page.clicks == []


async def test_switch_unknown_target_raises_with_options(monkeypatch):
    """④ 미존재 target — 실제 옵션 목록을 노출하고 클릭하지 않는다."""
    page = _UtPage(LIVE_OPTIONS, selected=2, panel_open=True)
    page.install_clock(monkeypatch)
    with pytest.raises(UserTypeError) as ei:
        await auth.switch_user_type(page, "총무")
    assert "SCM-구매" in str(ei.value)
    assert page.clicks == []


async def test_read_user_type_options_returns_empty_when_reader_unavailable():
    """리더가 못 읽으면 빈 목록 — 호출부는 레거시 폴백(target=라벨)으로 퇴화한다."""

    class _Blank:
        async def evaluate(self, js_src, arg=None):
            return None

    assert await auth.read_user_type_options(_Blank()) == []
