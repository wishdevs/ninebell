"""card_collect steps — 잔여 모달('예산현황' 지연 출현) 처리 회귀 테스트.

실전 런(2026-07-02): 카드팝업 '적용' 후 팝업이 먼저 닫히고 '예산현황' 모달이 늦게 떠서
apply_rows_to_document 가 즉시 ok 반환 → 모달이 화면을 덮은 채 증빙유형 02 선택 시도
→ TypeError 실패. 팝업 닫힘 후 잔여 모달 정리를 검증한다.
"""

from __future__ import annotations

import pytest

from app.agents.card_collect import js, steps

pytestmark = pytest.mark.asyncio


class _Mouse:
    def __init__(self, owner: "_LateModalPage"):
        self._owner = owner

    async def click(self, x, y):
        self._owner.clicks.append((x, y))
        # 열린 모달 위 '확인' 클릭 → 모달 닫힘.
        if self._owner.modals:
            self._owner.modals.pop(0)


class _Keyboard:
    def __init__(self, owner: "_LateModalPage"):
        self._owner = owner

    async def press(self, key):
        self._owner.keys.append(key)


class _LateModalPage:
    """적용 직후 팝업은 닫혔지만 '예산현황' 모달이 첫 스냅샷 시점에 뒤늦게 뜨는 fake."""

    def __init__(self, *, card_win: bool = False):
        self.clicks: list[tuple] = []
        self.keys: list[str] = []
        self.modals: list[dict] = []
        self._spawned = False
        self._card_win = card_win
        self.mouse = _Mouse(self)
        self.keyboard = _Keyboard(self)

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, script, arg=None):
        if script == js.CHECK_ROWS_JS:
            return {"ok": True, "checked": len(arg)}
        if script == js.CARD_WIN_EXISTS_JS:
            return self._card_win
        if script == js.MODALS_SNAPSHOT_JS:
            if not self._spawned:
                self._spawned = True
                self.modals = [{"title": "예산현황", "text": ""}]
            return list(self.modals)
        if script == js.MODAL_BTN_BOX_JS:
            # 열린 모달이 있을 때만 버튼 박스 반환('확인' 계열).
            if self.modals and arg in ("확인",):
                return {"x": 10, "y": 20, "title": self.modals[0]["title"]}
            return None
        # card_button_box_js("적용") 등 버튼 박스 생성 스크립트.
        if "적용" in script:
            return {"x": 1, "y": 2}
        return None


async def test_apply_rows_dismisses_late_budget_modal():
    """팝업 닫힘 후 지연 출현한 '예산현황' 모달을 닫고 ok 반환해야 한다."""
    page = _LateModalPage(card_win=False)
    r = await steps.apply_rows_to_document(page, [0, 1])
    assert r["ok"] is True
    assert page.modals == []  # 잔여 모달 정리됨
    assert any(m["title"] == "예산현황" for m in r.get("late_modals") or [])


async def test_save_document_dismisses_leftover_modal_before_f7():
    """F7 전에 잔여 모달을 닫아야 한다 — 모달이 F7 을 삼키면 미저장 가짜 성공이 된다."""
    page = _LateModalPage(card_win=False)
    r = await steps.save_document(page, confirm=True)
    assert r["ok"] is True
    assert page.keys == ["F7"]
    assert page.modals == []
    assert any(m["title"] == "예산현황" for m in r.get("pre_modals") or [])
    # 모달 클릭(정리)이 F7 이전에 일어났는지 — clicks 가 있고 keys 는 그 뒤에 눌림.
    assert page.clicks, "잔여 모달 '확인' 클릭이 없었다"
