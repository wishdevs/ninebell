"""expense_card.tools 단위테스트 — page 조작 도구 디스패치(실 브라우저 없이 mock page).

FakePage.evaluate 는 스크립트 객체 identity 로 응답을 라우팅한다(tools 의 JS 상수와 동일
객체). mouse/keyboard/wait 는 no-op 기록. Gemini·실 옴니솔은 쓰지 않는다.
저장(F7) 액션이 없음을 코드 경로로 확인(어떤 도구도 BTN_SAVE 를 클릭하지 않는다).
"""

from __future__ import annotations

from typing import Any, Callable

import app.agents.expense_card.tools as T
from nbkit.omnisol import js_lib


class _FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class _FakeKeyboard:
    def __init__(self) -> None:
        self.presses: list[str] = []

    async def press(self, key: str) -> None:
        self.presses.append(key)


class FakePage:
    """evaluate 를 handler(script, arg)로 위임하는 최소 Playwright Page 대역."""

    def __init__(self, handler: Callable[[Any, Any], Any]) -> None:
        self._handler = handler
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard()

    async def evaluate(self, script: Any, arg: Any = None) -> Any:
        return self._handler(script, arg)

    async def wait_for_timeout(self, _ms: int) -> None:
        return None


# ── fill_dropdown / fill_text (단일 evaluate 도구) ────────────────────────────
async def test_do_fill_dropdown_ok_and_fail():
    ok_page = FakePage(lambda s, a: {"ok": True, "text": "공제"})
    res = await T.do_fill_dropdown(ok_page, "부가세구분", "공제")
    assert res.startswith("ok(미검증)")
    assert "공제" in res

    fail_page = FakePage(lambda s, a: {"ok": False, "reason": "select-not-found"})
    res2 = await T.do_fill_dropdown(fail_page, "부가세구분", "공제")
    assert res2.startswith("fail(미검증)")
    assert "select-not-found" in res2


async def test_do_fill_text_ok_and_fail():
    ok_page = FakePage(lambda s, a: {"ok": True, "id": "note1"})
    assert (await T.do_fill_text(ok_page, "적요", "출장비")).startswith("ok(미검증)")

    fail_page = FakePage(lambda s, a: {"ok": False, "reason": "input-not-found"})
    assert (await T.do_fill_text(fail_page, "적요", "출장비")).startswith("fail(미검증)")


# ── budget (예산단위) — unsupported / ambiguous / ok ──────────────────────────
async def test_do_budget_unsupported_no_page_calls():
    def _boom(_s, _a):  # noqa: ANN001
        raise AssertionError("unsupported 항목은 page 를 건드리면 안 됨")

    status, msg = await T.do_budget(FakePage(_boom), "택시비", "")
    assert status == "unsupported"
    assert "택시비" in msg


async def test_do_budget_ambiguous_asks_je_pan():
    def handler(script, arg):  # noqa: ANN001
        if script is T._KWINDOW_OVER1_JS:
            return False  # close_top_popup: 모달 위 팝업 없음
        if script is T.CARD_PICKER_BOX_JS:
            return {"x": 10, "y": 20} if arg == "예산단위" else None
        if script is T._KWINDOW_ANY_JS:
            return True  # 팝업 열림
        if script is T.POPUP_SET_KEYWORD_JS:
            return True
        if script is T.POPUP_QUERY_BTN_JS:
            return {"x": 1, "y": 2}
        if script is T.BUDGET_READ_JS:
            return {
                "dept": "인사기획팀",
                "rows": [
                    {"idx": 0, "bg": "인사기획팀", "biz": "b1", "acct": "(제)복리후생비-석식"},
                    {"idx": 1, "bg": "인사기획팀", "biz": "b2", "acct": "(판)복리후생비-석식"},
                ],
            }
        return None

    status, msg = await T.do_budget(FakePage(handler), "야근식대", "")
    assert status == "ambiguous"
    assert "제조/판매" in msg


async def test_do_budget_ok_selects_and_applies():
    page = None

    def handler(script, arg):  # noqa: ANN001
        if script is T._KWINDOW_OVER1_JS:
            return False
        if script is T.CARD_PICKER_BOX_JS:
            return {"x": 10, "y": 20}
        if script is T._KWINDOW_ANY_JS:
            return True
        if script is T.POPUP_SET_KEYWORD_JS:
            return True
        if script is T.POPUP_QUERY_BTN_JS:
            return {"x": 1, "y": 2}
        if script is T.BUDGET_READ_JS:
            return {
                "dept": "인사기획팀",
                "rows": [{"idx": 0, "bg": "인사기획팀", "biz": "b1", "acct": "(제)복리후생비-석식"}],
            }
        if script is T.BUDGET_SELECT_JS:
            return {"ok": True}
        if script is T.CARD_POPUP_APPLY_BOX_JS:
            return {"x": 3, "y": 4}
        return None

    page = FakePage(handler)
    status, msg = await T.do_budget(page, "야근식대", "제조")
    assert status == "ok"
    assert "복리후생비-석식" in msg
    # '적용' 버튼 좌표를 실클릭했는지(모달 적용까지만).
    assert (3, 4) in page.mouse.clicks


# ── account (예산단위 후 자동축소 계정) ──────────────────────────────────────
async def test_do_account_ok_autoselect():
    calls = {"over1": 0}

    def handler(script, arg):  # noqa: ANN001
        if script is T._KWINDOW_OVER1_JS:
            calls["over1"] += 1
            return calls["over1"] > 1  # 첫 호출(close_top_popup)=False, 이후 열림=True
        if script is T.CARD_PICKER_BOX_JS:
            return {"x": 10, "y": 20}
        if script is T.ACCOUNT_READ_JS:
            return {"n": 1, "cols": ["ACCT_NM"], "rows": [{"ACCT_NM": "복리후생비-석식"}]}
        if script is T.ACCOUNT_SELECT_JS:
            return {"ok": True}
        if script is T.CARD_POPUP_APPLY_BOX_JS:
            return {"x": 5, "y": 6}
        return None

    status, msg = await T.do_account(FakePage(handler))
    assert status == "ok"
    assert "복리후생비-석식" in msg
    assert "자동" in msg


# ── fill_search — 검증(프로젝트) vs 미검증 경로 분기 ──────────────────────────
async def test_do_fill_search_project_picker_missing_uses_verified_js():
    # field '프로젝트' → 검증 경로: §B PROJECT_PICKER_BOX_JS 를 쓰고, 버튼 없으면 '미검증' 표기 없음.
    seen = {"used_verified": False}

    def handler(script, arg):  # noqa: ANN001
        if script is js_lib.PROJECT_PICKER_BOX_JS:
            seen["used_verified"] = True
            return None
        if script is T.CARD_PICKER_BOX_JS:
            raise AssertionError("프로젝트는 미검증 CARD_PICKER_BOX_JS 를 쓰면 안 됨")
        return None

    res = await T.do_fill_search(FakePage(handler), "프로젝트", "", "SPARES_ACM")
    assert seen["used_verified"] is True
    assert res.startswith("fail")
    assert "미검증" not in res  # 검증 경로 → '미검증' 꼬리표 없음


async def test_do_fill_search_unverified_missing_button_marks_scaffold():
    res = await T.do_fill_search(FakePage(lambda s, a: None), "거래처", "", "ACME")
    assert res.startswith("fail")
    assert "미검증" in res  # 미검증 필드 표기 보존


async def test_do_fill_search_unverified_success_path():
    def handler(script, arg):  # noqa: ANN001
        if script is T.CARD_PICKER_BOX_JS:
            return {"x": 10, "y": 20}
        if script is T._KWINDOW_ANY_JS:
            return True
        if script is T.CARD_POPUP_SELECT_JS:
            return {"ok": True}
        if script is T.CARD_POPUP_APPLY_BOX_JS:
            return {"x": 7, "y": 8}
        return None

    page = FakePage(handler)
    res = await T.do_fill_search(page, "거래처", "", "ACME")
    assert res.startswith("ok(미검증)")
    assert (7, 8) in page.mouse.clicks


# ── close_top_popup — 모달만 있을 땐 no-op ────────────────────────────────────
async def test_close_top_popup_noop_when_only_modal():
    page = FakePage(lambda s, a: False)  # _KWINDOW_OVER1 → False(팝업 없음)
    await T.close_top_popup(page)
    assert page.mouse.clicks == []
    assert page.keyboard.presses == []


async def test_close_top_popup_clicks_close_when_popup_present():
    def handler(script, arg):  # noqa: ANN001
        if script is T._KWINDOW_OVER1_JS:
            return True
        if script is T.POPUP_CLOSE_BTN_JS:
            return {"x": 9, "y": 9}
        return None

    page = FakePage(handler)
    await T.close_top_popup(page)
    assert (9, 9) in page.mouse.clicks
