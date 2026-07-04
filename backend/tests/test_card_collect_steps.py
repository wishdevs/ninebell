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


class _SaveErrorPage(_LateModalPage):
    """F7 후 '[오류]' 모달이 뜨는 fake — 저장 거부 케이스(실측: 승인취소 계정 불일치)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._spawned = True  # 부모의 pre-F7 지연 모달 스폰 비활성화
        self._err_spawned = False

    async def evaluate(self, script, arg=None):
        if script == js.MODALS_SNAPSHOT_JS and "F7" in self.keys and not self._err_spawned:
            self._err_spawned = True
            self.modals = [{"title": "오류", "text": "[승인번호: X, 승인취소] 승인 건 계정과 다릅니다."}]
            return list(self.modals)
        return await super().evaluate(script, arg)


class _ToastPage(_LateModalPage):
    """F7 후 모달 없이 인라인 검증 토스트만 뜨는 fake — 필수값 누락 미저장 케이스(실측 2026-07-03)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._spawned = True  # 부모의 예산현황 지연 모달 비활성화

    async def evaluate(self, script, arg=None):
        if script == js.VALIDATION_TOAST_JS and "F7" in self.keys:
            return ["상세그리드에 필수 값이 입력되지 않은 항목이 있습니다"]
        if script == js.MODALS_SNAPSHOT_JS:
            return []  # 토스트는 모달이 아님
        return await super().evaluate(script, arg)


async def test_save_document_reports_validation_toast_as_failure():
    """F7 후 인라인 '필수 값…' 토스트 관찰 시 ok:False — 미저장 가짜 성공 방지."""
    page = _ToastPage(card_win=False)
    r = await steps.save_document(page, confirm=True)
    assert r["ok"] is False
    assert "필수 값" in r["reason"]
    assert page.keys == ["F7"]


async def test_save_document_reports_error_modal_as_failure():
    """F7 후 '오류' 모달 관찰 시 ok:False + 모달 전문 — 미저장 가짜 성공 방지."""
    page = _SaveErrorPage(card_win=False)
    r = await steps.save_document(page, confirm=True)
    assert r["ok"] is False
    assert "승인 건 계정과 다릅니다" in r["reason"]


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


class _PickerSeqPage:
    """PICKER_ROWCOUNT_JS 가 호출마다 시퀀스 값을 돌려주는 fake — 조건 대기 헬퍼 검증."""

    def __init__(self, seq):
        self._seq = list(seq)
        self.polls = 0

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, script, arg=None):
        if script == js.PICKER_ROWCOUNT_JS:
            self.polls += 1
            return self._seq.pop(0) if self._seq else -1
        return None


async def test_wait_picker_rows_stable_returns_on_stability():
    """rowcount 준비(>=0) 후 2회 연속 동일하면 즉시 반환 — 고정 대기 대체 검증."""
    page = _PickerSeqPage([-2, -2, 5, 5])  # 로딩→로딩→5→5(안정)
    n = await steps._wait_picker_rows_stable(page, cap_ms=3_000, interval_ms=200)
    assert n == 5
    assert page.polls == 4  # 4번째 폴에서 안정 확정(총 ~800ms 상당 — 고정 1.5~1.8s 미만)


async def test_wait_picker_rows_stable_min_ms_defers_stability():
    """min_ms 이전의 '옛 rowcount 안정'은 무시 — 검색 재조회 오인 방지."""
    page = _PickerSeqPage([7, 7, 7, 3, 3])  # 600ms 전 7(옛값)→재조회 후 3(새값)
    n = await steps._wait_picker_rows_stable(page, cap_ms=2_000, interval_ms=200, min_ms=600)
    assert n == 3


async def test_wait_picker_closed_returns_when_gone():
    page = _PickerSeqPage([4, 4, -1])  # 열림→열림→닫힘
    await steps._wait_picker_closed(page, cap_ms=1_500, interval_ms=150)
    assert page.polls == 3
