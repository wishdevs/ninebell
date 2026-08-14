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


class _CardSubPage:
    """카드 서브팝업 fake — 돋보기·by-name·전체선택·적용을 시퀀스로 흉내낸다."""

    def __init__(self, *, matched: int, total: int = 5):
        self._matched = matched
        self._total = total
        self.by_name_called = False
        self.by_name_arg = None  # by-name JS 로 전달된 owners 인자(변형 목록 검증용)
        self.all_called = False
        self.clicks: list[tuple] = []
        self.mouse = self  # click 을 자기 자신에서 받음

    async def wait_for_timeout(self, ms):
        return None

    async def click(self, x, y):  # mouse.click
        self.clicks.append((x, y))

    async def evaluate(self, script, arg=None):
        if script == js.CARD_SEARCH_BTN_JS:
            return {"x": 1, "y": 2}  # 돋보기 버튼
        if script == js.CARD_SUB_SELECT_BY_NAME_JS:
            self.by_name_called = True
            self.by_name_arg = arg
            return {"ok": True, "n": self._total, "matched": self._matched, "checked": self._matched}
        if script == js.CARD_SUB_SELECT_ALL_JS:
            self.all_called = True
            return {"ok": True, "n": self._total, "checked": self._total}
        if script == js.CARD_SUB_APPLY_BTN_JS:
            return {"x": 3, "y": 4}
        return None


async def test_select_cards_by_name_when_match():
    """일반 모드(own_only=True): 본인 이름과 일치하는 카드만 선택(by='name')."""
    page = _CardSubPage(matched=2)
    r = await steps.select_all_cards(page, owner_name="이트라이브2", own_only=True)
    assert r["ok"] and r["by"] == "name" and r["checked"] == 2
    assert page.by_name_called and not page.all_called  # 전체선택 미호출


async def test_select_cards_own_only_zero_match_falls_back_to_all():
    """일반 모드 본인 카드 0건 — **전체선택으로 폴백**(사용자 확정 2026-08-03).

    법인 공용 카드만 쓰는 계정은 본인 명의 카드가 아예 없어(카드명 괄호에 개인명 없음)
    하드 실패시키면 실행 자체가 막힌다. 처리 대상은 뒤의 그리드 개입에서 사용자가 확정하므로
    전체를 담는 것은 후보 제시다. 폴백 사실은 warn 으로 반드시 남아야 한다(안내 노출 근거).
    """
    page = _CardSubPage(matched=0)
    r = await steps.select_all_cards(page, owner_name="이트라이브2", own_only=True)
    assert r["ok"] is True and r["by"] == "all"
    assert page.by_name_called and page.all_called  # 본인 매칭 시도 후 전체선택
    assert "본인 카드 0장" in (r.get("warn") or "")  # 폴백 사유가 로그로 노출된다


async def test_select_cards_own_only_without_owner_fails():
    """일반 모드인데 본인 판정 이름이 없으면 즉시 실패 — 팝업도 열지 않는다."""
    page = _CardSubPage(matched=3)
    r = await steps.select_all_cards(page, owner_name=None, own_only=True)
    assert r["ok"] is False and "사용자 이름" in r["reason"]
    assert not page.by_name_called and not page.all_called and page.clicks == []


async def test_select_cards_all_when_no_owner():
    """디버그 모드(own_only=False 기본)면 by-name 미호출·전체선택."""
    page = _CardSubPage(matched=3)
    r = await steps.select_all_cards(page, owner_name=None)
    assert r["ok"] and r["by"] == "all"
    assert not page.by_name_called and page.all_called


async def test_select_cards_passes_variant_list_to_js():
    """이름 변형 목록을 주면 JS 에 배열 그대로 전달된다(빈 값·공백 정리 포함)."""
    page = _CardSubPage(matched=1)
    r = await steps.select_all_cards(page, owner_name=["sdh", " 석대현 ", ""], own_only=True)
    assert r["ok"] and r["by"] == "name"
    assert page.by_name_arg == ["sdh", "석대현"]


async def test_owner_name_variants_includes_job_title_form():
    """로그인ID + 순수 이름 + '이름 직책' 변형을 중복 없이 만든다(사용자 요청 2026-07-29)."""
    assert steps.owner_name_variants("sdh", "석대현", "프로") == ["sdh", "석대현", "석대현 프로"]
    # 직책 없으면 '이름 직책' 변형 없음, 이름 없으면 로그인ID 만.
    assert steps.owner_name_variants("sdh", "석대현", None) == ["sdh", "석대현"]
    assert steps.owner_name_variants("sdh", None, "프로") == ["sdh"]
    # 로그인ID == 이름(이 ERP 관례)이면 중복 제거.
    assert steps.owner_name_variants("석대현", "석대현", "프로") == ["석대현", "석대현 프로"]


# ══════════════════════════════════════════════════════════════════════════════
# 확인(verify) 커널 계약 테스트 — "세팅했다"가 아니라 "반영됐다"를 스텝이 책임지는가.
#   반영 성공 → ok / 반영 실패(값 다름·팝업 미개폐) → 하드 실패 / 리더 미독해 → warn 후 진행.
# 페이크는 실물 시맨틱을 지킨다: k-window 스택(POPUP_COUNT), 카드 서브팝업 존재, 그리드
# rowcount·NOTE_DC, 코드피커 팝업 개폐 — 조작이 상태를 실제로 바꿔야만 확인이 통과한다.
# ══════════════════════════════════════════════════════════════════════════════
from nbkit.omnisol import js_lib  # noqa: E402


class _Mouse2:
    def __init__(self, owner: "_OmniPage"):
        self._o = owner

    async def click(self, x, y):
        self._o.clicks.append((x, y))
        handler = self._o.buttons.get((x, y))
        if handler:
            handler()


class _Keyboard2:
    def __init__(self, owner: "_OmniPage"):
        self._o = owner

    async def press(self, key, delay=None):
        self._o.keys.append(key)


class _OmniPage:
    """법인카드 팝업 fake — 팝업 스택·그리드·필드값을 상태로 갖는 실물 시맨틱 페이크.

    ``popups`` 는 떠 있는 k-window 제목(맨 끝이 최상단). '법인카드' 팝업이 바닥에 깔려 있고
    서브팝업/코드피커/'예산현황' 확인창이 그 위에 쌓인다 — 실제 화면과 같은 구조라
    POPUP_COUNT 증가/감소 확인이 의미를 갖는다.
    """

    def __init__(self):
        self.popups: list[str] = ["법인카드"]
        self.clicks: list[tuple] = []
        self.keys: list[str] = []
        self.buttons: dict[tuple, object] = {}
        self.notes: dict[int, str] = {}
        self.rowcount = 0
        self.fields: dict[str, object] = {}  # scope/selector → 표시값
        self.period: dict[str, str] = {}
        self.note_sink: str | None = None  # setValue 가 값을 절삭·무시하는 그리드 흉내
        self.mouse = _Mouse2(self)
        self.keyboard = _Keyboard2(self)

    # ── 헬퍼 ──────────────────────────────────────────────────────────────────
    def _rows(self, limit):
        n = self.rowcount
        out = [{"i": i, "NOTE_DC": self.notes.get(i)} for i in range(min(n, limit or n))]
        return {"rows": n, "list": out}

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, script, arg=None):
        if script == js_lib.POPUP_COUNT_JS:
            return len(self.popups)
        if script == js_lib.SCOPED_FIELD_VALUE_JS:
            if "법인카드" not in self.popups:
                return None  # win 미매치 = 확인 불가
            key = (arg or {}).get("scope") or (arg or {}).get("selector") or ""
            return self.fields.get(key)
        if script == js.CARD_WIN_EXISTS_JS:
            return "법인카드" in self.popups
        if script == js.CARD_SUB_EXISTS_JS:
            return "카드" in self.popups
        if script == js.CARD_SEARCH_BTN_JS:
            return {"x": 11, "y": 11}
        if script == js.CARD_SUB_APPLY_BTN_JS:
            return {"x": 12, "y": 12}
        if script == js.ROWCOUNT_JS:
            return self.rowcount
        if script == js.QUERY_BTN_JS:
            return {"x": 21, "y": 21}
        if script == js.READ_ROWS_JS:
            return self._rows(arg)
        if script == js.NOTE_SET_JS:
            row, text = arg
            self.notes[row] = self.note_sink if self.note_sink is not None else text
            return {"ok": True, "after": self.notes[row]}
        if script == js.PERIOD_SET_JS:
            start, end = arg
            self.period = {"start": start, "end": end}
            return {"start": start, "end": end}
        if script == js_lib.PERIOD_VALUE_JS:
            if not self.period:
                return {"found": False, "reason": "no-field", "now": "202607"}
            return {"found": True, "values": [self.period["start"], self.period["end"]]}
        if script == js.CHECK_ROWS_JS:
            return {"ok": True, "checked": len(arg)}
        if script == js.BUDGET_CONFIRM_JS:
            if "예산현황" not in self.popups:
                return {"n": 0}
            self.popups.remove("예산현황")
            return {"n": 1, "clicked": "확인"}
        if "일괄적용" in script:
            return {"x": 31, "y": 31}
        if "닫기" in script:
            return {"x": 41, "y": 41}
        return None


# ── select_all_cards ──────────────────────────────────────────────────────────
class _CardSelectPage(_OmniPage):
    """돋보기 → '카드' 서브팝업 → 체크 → 적용(닫힘·폼 반영)의 실물 순서를 흉내낸다."""

    def __init__(self, *, total=5, matched=0, checked_delta=0, opens=True, closes=True,
                 display="1234-****-****-5678"):
        super().__init__()
        self._total = total
        self._matched = matched
        self._delta = checked_delta  # 체크 수가 기대와 어긋나는 사고(0장 체크 등)
        self._closes = closes
        self.fields[".dews-multicodepicker-text"] = "" if display is None else display
        self._display_after_apply = display
        self.buttons[(11, 11)] = self._open_sub if opens else (lambda: None)
        self.buttons[(12, 12)] = self._apply_sub

    def _open_sub(self):
        self.popups.append("카드")

    def _apply_sub(self):
        if self._closes and "카드" in self.popups:
            self.popups.remove("카드")
            if self._display_after_apply is not None:
                self.fields[".dews-multicodepicker-text"] = self._display_after_apply

    async def evaluate(self, script, arg=None):
        if script == js.CARD_SUB_SELECT_ALL_JS:
            return {"ok": True, "n": self._total, "checked": self._total + self._delta}
        if script == js.CARD_SUB_SELECT_BY_NAME_JS:
            return {"ok": True, "n": self._total, "matched": self._matched,
                    "checked": self._matched + self._delta}
        return await super().evaluate(script, arg)


async def test_select_all_cards_ok_when_popup_opens_checks_and_closes():
    """서브팝업 오픈·체크 수 일치·닫힘·폼 표시값까지 확인되면 ok(verified=True, warn 없음)."""
    page = _CardSelectPage(total=4)
    r = await steps.select_all_cards(page, owner_name=None)
    assert r["ok"] is True and r["by"] == "all" and r["checked"] == 4
    assert r["verified"] is True and "warn" not in r
    assert page.popups == ["법인카드"]  # 서브팝업이 실제로 닫혔다


async def test_select_all_cards_fails_when_checked_count_mismatches():
    """checkAll 은 호출됐지만 실제 체크가 0장이면 하드 실패 — 0장 선택 조용한 통과 차단."""
    page = _CardSelectPage(total=4, checked_delta=-4)  # n=4 인데 checked=0
    r = await steps.select_all_cards(page, owner_name=None)
    assert r["ok"] is False and "체크 불일치" in r["reason"]


async def test_select_all_cards_fails_when_sub_popup_not_opened():
    """돋보기를 눌렀는데 서브팝업이 안 뜨면 하드 실패 — 잔여 팝업 오독 차단."""
    page = _CardSelectPage(total=4, opens=False)
    r = await steps.select_all_cards(page, owner_name=None)
    assert r["ok"] is False and "서브팝업이 열리지 않" in r["reason"]


async def test_select_all_cards_fails_when_sub_popup_stays_open():
    """'적용' 후에도 서브팝업이 남으면 하드 실패 — 예전엔 {ok:True} 로 성공 오보했다."""
    page = _CardSelectPage(total=4, closes=False)
    r = await steps.select_all_cards(page, owner_name=None)
    assert r["ok"] is False and "닫히지 않" in r["reason"]


async def test_select_all_cards_warns_when_display_unreadable():
    """카드번호 표시값을 못 읽으면(리더 null) 하드 실패가 아니라 warn + verified=False."""
    page = _CardSelectPage(total=4, display=None)
    page.fields[".dews-multicodepicker-text"] = None
    r = await steps.select_all_cards(page, owner_name=None)
    assert r["ok"] is True and r["verified"] is False and r.get("warn")


# ── set_period ────────────────────────────────────────────────────────────────
class _PeriodRevertPage(_OmniPage):
    """periodpicker 가 change 핸들러로 값을 되돌리는 위젯(동기 readback 으로는 못 잡는 사고)."""

    def __init__(self, *, revert_to=("2026-05-01", "2026-05-31"), forever=True):
        super().__init__()
        self.period = {"start": revert_to[0], "end": revert_to[1]}
        self._revert = revert_to
        self._forever = forever
        self._sets = 0

    async def evaluate(self, script, arg=None):
        if script == js.PERIOD_SET_JS:
            start, end = arg
            self._sets += 1
            if self._forever or self._sets < 2:
                self.period = {"start": self._revert[0], "end": self._revert[1]}  # 되돌림
            else:
                self.period = {"start": start, "end": end}  # 재세팅에서 붙음
            return {"start": start, "end": end}  # 같은 tick readback 은 늘 성공으로 보인다
        return await super().evaluate(script, arg)


async def test_set_period_ok_when_widget_keeps_value():
    page = _OmniPage()
    r = await steps.set_period(page, "2026-07-01", "2026-07-27")
    assert r["ok"] is True and "warn" not in r
    assert r["display"] == ["2026-07-01", "2026-07-27"]


async def test_set_period_fails_when_widget_reverts_value():
    """위젯이 값을 되돌리면 하드 실패 — 기간이 틀리면 수집 대상 자체가 달라진다."""
    page = _PeriodRevertPage()
    r = await steps.set_period(page, "2026-07-01", "2026-07-27")
    assert r["ok"] is False and "승인일 기간" in r["reason"]


async def test_set_period_reapplies_and_recovers():
    """재시도 때 **재세팅**해서 값이 붙으면 ok — 되돌려지는 값 전용 reapply 경로."""
    page = _PeriodRevertPage(forever=False)
    r = await steps.set_period(page, "2026-07-01", "2026-07-27")
    assert r["ok"] is True and page.period == {"start": "2026-07-01", "end": "2026-07-27"}


async def test_set_period_warns_when_reader_cannot_find_field():
    """periodpicker 를 못 읽으면(found:false) 확인 불가 → warn 후 진행."""

    class _Blind(_OmniPage):
        async def evaluate(self, script, arg=None):
            if script == js_lib.PERIOD_VALUE_JS:
                return {"found": False, "reason": "no-field", "now": "202607"}
            return await super().evaluate(script, arg)

    r = await steps.set_period(_Blind(), "2026-07-01", "2026-07-27")
    assert r["ok"] is True and r.get("warn")


# ── run_query ─────────────────────────────────────────────────────────────────
class _QueryPage(_OmniPage):
    """조회 클릭 후 서버 응답이 늦게 도착하는 그리드 — 도착 전 rowcount 는 클릭 전 값 그대로."""

    def __init__(self, *, before: int, after: int, arrive_on: int):
        super().__init__()
        self.rowcount = before
        self._after = after
        self._arrive_on = arrive_on  # 몇 번째 ROWCOUNT 읽기부터 새 결과가 보이는가
        self.reads = 0
        self.buttons[(21, 21)] = lambda: None

    async def evaluate(self, script, arg=None):
        if script == js.ROWCOUNT_JS:
            self.reads += 1
            if self.reads > self._arrive_on:
                self.rowcount = self._after
            return self.rowcount
        return await super().evaluate(script, arg)


async def test_run_query_waits_for_new_result_instead_of_stale_grid():
    """1차 결과(3건)가 남은 상태의 2차 조회 — 새 결과(2건)가 올 때까지 스테일을 확정하지 않는다."""
    page = _QueryPage(before=3, after=2, arrive_on=2)  # 첫 스냅샷+1회는 옛 값
    rows = await steps.run_query(page)
    assert rows == 2


async def test_run_query_holds_zero_until_schedule_exhausted():
    """0건은 스케줄을 전부 소진한 뒤에만 확정 — 서버 응답 전 '0건' 조기 확정 차단."""
    page = _QueryPage(before=0, after=0, arrive_on=99)
    rows = await steps.run_query(page)
    assert rows == 0
    # 첫 스냅샷 1회 + 확인 커널 HEAVY 4회 = 5회 (조기 확정이면 2회에서 끝났다)
    assert page.reads == 1 + 4


async def test_run_query_returns_minus_one_when_grid_unreadable():
    class _Dead(_QueryPage):
        async def evaluate(self, script, arg=None):
            if script == js.ROWCOUNT_JS:
                return -1
            return await super().evaluate(script, arg)

    assert await steps.run_query(_Dead(before=0, after=0, arrive_on=0)) == -1


# ── set_note / verify_notes ───────────────────────────────────────────────────
async def test_set_note_ok_when_cell_takes_value():
    page = _OmniPage()
    page.rowcount = 3
    r = await steps.set_note(page, 1, "7월 회식비")
    assert r["ok"] is True and r["after"] == "7월 회식비"


async def test_set_note_fails_when_grid_truncates_value():
    """setValue 는 ok 인데 셀이 값을 절삭·무시하면 하드 실패 — 적요는 전표에 남는 데이터다."""
    page = _OmniPage()
    page.rowcount = 3
    page.note_sink = "7월 회"  # 그리드가 절삭
    r = await steps.set_note(page, 1, "7월 회식비")
    assert r["ok"] is False and "적요" in r["reason"]


async def test_verify_notes_reapplies_when_picker_reverted_note():
    """피커 '적용'이 적요를 되돌렸으면 재세팅으로 복구하고 ok — cascade 규율."""
    page = _OmniPage()
    page.rowcount = 6
    page.notes = {0: "", 2: "", 5: ""}  # 피커 적용으로 되돌려진 상태
    r = await steps.verify_notes(page, [0, 2, 5], "회식")
    assert r["ok"] is True and page.notes == {0: "회식", 2: "회식", 5: "회식"}


async def test_verify_notes_fails_when_note_cannot_survive():
    """재세팅해도 되돌려지면 하드 실패 — 적요 없는 전표가 조용히 반영되는 것을 막는다."""
    page = _OmniPage()
    page.rowcount = 6
    page.note_sink = ""  # 어떤 setValue 도 붙지 않는 그리드
    r = await steps.verify_notes(page, [0, 2], "회식")
    assert r["ok"] is False and "적요 생존" in r["reason"]


async def test_verify_notes_warns_when_rows_unreadable():
    """그리드를 못 읽으면 확인 불가 → warn 후 진행(리더 오탐이 플로우를 끊지 않게)."""

    class _Blind(_OmniPage):
        async def evaluate(self, script, arg=None):
            if script == js.READ_ROWS_JS:
                return {"rows": -1, "err": "no-win"}
            return await super().evaluate(script, arg)

    r = await steps.verify_notes(_Blind(), [0], "회식")
    assert r["ok"] is True and r.get("warn")


# ── apply_rows('예산현황' 확인창) ──────────────────────────────────────────────
class _ApplyRowsPage(_OmniPage):
    def __init__(self, *, spawns=True, closable=True):
        super().__init__()
        self._spawns = spawns
        self._closable = closable
        self.buttons[(31, 31)] = self._batch_apply

    def _batch_apply(self):
        if self._spawns:
            self.popups.append("예산현황")

    async def evaluate(self, script, arg=None):
        if script == js.BUDGET_CONFIRM_JS and not self._closable:
            return {"n": 1, "clicked": None}  # 확인 버튼을 못 찾음
        return await super().evaluate(script, arg)


async def test_apply_rows_confirms_budget_dialog():
    page = _ApplyRowsPage()
    r = await steps.apply_rows(page, [0, 1])
    assert r["ok"] is True and r["budget_confirm"] is True and "warn" not in r
    assert page.popups == ["법인카드"]  # 확인창이 실제로 닫혔다


async def test_apply_rows_fails_when_budget_dialog_cannot_be_closed():
    """확인창이 떴는데 못 닫으면 하드 실패 — 남은 창을 다음 피커가 읽어 0건이 된다."""
    page = _ApplyRowsPage(closable=False)
    r = await steps.apply_rows(page, [0, 1])
    assert r["ok"] is False and "예산현황" in r["reason"]


async def test_apply_rows_warns_when_budget_dialog_never_appears():
    """확인창이 안 뜨는 세션은 확인 불가 → warn 후 진행(하드 실패로 만들지 않는다)."""
    page = _ApplyRowsPage(spawns=False)
    r = await steps.apply_rows(page, [0, 1])
    assert r["ok"] is True and r["budget_confirm"] is False and "미출현" in r["warn"]


# ── close_card_popup ──────────────────────────────────────────────────────────
async def test_close_card_popup_fails_when_window_remains():
    page = _OmniPage()
    page.buttons[(41, 41)] = lambda: None  # 닫기 클릭이 먹히지 않음
    r = await steps.close_card_popup(page)
    assert r["ok"] is False and "남아 있음" in r["reason"]


async def test_close_card_popup_ok_when_window_gone():
    page = _OmniPage()
    page.buttons[(41, 41)] = lambda: page.popups.remove("법인카드")
    r = await steps.close_card_popup(page)
    assert r["ok"] is True


# ── dismiss_modals_verified ───────────────────────────────────────────────────
async def test_dismiss_modals_verified_warns_when_popups_do_not_shrink(monkeypatch):
    """'닫았다'고 보고했는데 팝업이 안 줄면 warn — 남은 모달이 다음 조작을 가로챈다."""
    page = _OmniPage()
    page.popups = ["법인카드", "예산현황"]

    async def _fake_dismiss(p, rounds=3):
        return ["예산현황"]  # 닫았다고 보고만 하고 실제로는 안 닫힘

    monkeypatch.setattr(steps, "dismiss_blocking_modals", _fake_dismiss)
    r = await steps.dismiss_modals_verified(page)
    assert r["cleared"] == ["예산현황"] and "줄지 않았" in r["warn"]


async def test_dismiss_modals_verified_silent_when_popups_shrink(monkeypatch):
    page = _OmniPage()
    page.popups = ["법인카드", "예산현황"]

    async def _fake_dismiss(p, rounds=3):
        page.popups.remove("예산현황")
        return ["예산현황"]

    monkeypatch.setattr(steps, "dismiss_blocking_modals", _fake_dismiss)
    r = await steps.dismiss_modals_verified(page)
    assert r["cleared"] == ["예산현황"] and "warn" not in r


# ── fill_budget_codepicker(코드피커 오픈·적용·닫힘·폼 반영) ─────────────────────
class _PickerPage(_OmniPage):
    """예산단위 코드피커 fake — 돋보기로 팝업이 뜨고 '적용'으로 닫히며 폼에 표시값이 붙는다.

    ⚠ 이 자리가 위험한 이유: 코드피커/모달 JS 는 '최근 열린 non-법인카드 k-window'를 읽으므로
    팝업이 안 뜨거나 안 닫히면 다음 조작이 엉뚱한 창을 읽는다(실측 사고). 그래서 개폐를
    팝업 개수로 확인한다 — 페이크도 같은 시맨틱(popups 스택)을 지킨다.
    """

    def __init__(self, *, opens=True, has_apply=True, closes=True, display="본사 · 2026 · 복리후생비"):
        super().__init__()
        self._opens = opens
        self._has_apply = has_apply
        self._closes = closes
        self._display = display
        self.buttons[(51, 51)] = self._open
        self.buttons[(52, 52)] = self._apply

    def _open(self):
        if self._opens:
            self.popups.append("예산단위")

    def _apply(self):
        if self._closes and "예산단위" in self.popups:
            self.popups.remove("예산단위")
            self.fields[steps.BUDGET_SCOPE] = self._display

    async def evaluate(self, script, arg=None):
        if "bg_cd-wrapper" in script:
            return {"x": 51, "y": 51}
        if script == js_lib.PICKER_ROWCOUNT_JS:
            return 1 if "예산단위" in self.popups else -1
        if script == js_lib.PICKER_SEARCH_JS:
            return {"ok": True}
        if script == js_lib.PICKER_READ_MULTI_JS:
            return {"rows": 1, "options": [
                {"i": 0, "BG_CD": "2006", "BG_NM": "본사", "BIZPLAN_NM": "2026", "BGACCT_NM": "복리후생비"}
            ]}
        if script == js_lib.PICKER_SELECT_JS:
            return {"ok": True}
        if script == js_lib.PICKER_APPLY_BTN_JS:
            return {"x": 52, "y": 52} if self._has_apply else None
        if script == js_lib.PICKER_CLOSE_JS:
            if "예산단위" in self.popups:
                self.popups.remove("예산단위")
            return True
        return await super().evaluate(script, arg)


_BG_COMBO = {"name": "본사", "bizplanNm": "2026", "bgacctNm": "복리후생비"}


async def test_fill_budget_codepicker_ok_when_applied_to_form():
    page = _PickerPage()
    r = await steps.fill_budget_codepicker(page, _BG_COMBO)
    assert r["ok"] is True and r["code"] == "2006"
    assert r["verified"] is True and "warn" not in r
    assert page.popups == ["법인카드"]  # 피커가 실제로 닫혔다


async def test_fill_budget_codepicker_fails_when_apply_button_missing():
    """'적용' 버튼이 없으면 선택이 폼에 안 붙는다 — 예전엔 {ok:True, code, name} 로 오보했다."""
    page = _PickerPage(has_apply=False)
    r = await steps.fill_budget_codepicker(page, _BG_COMBO)
    assert r["ok"] is False and "적용" in r["reason"]


async def test_fill_budget_codepicker_fails_when_picker_stays_open():
    """'적용' 후에도 피커가 남으면 하드 실패 — 다음 피커가 이 창을 읽어 0건이 된다."""
    page = _PickerPage(closes=False)
    r = await steps.fill_budget_codepicker(page, _BG_COMBO)
    assert r["ok"] is False and "닫히지 않" in r["reason"]


async def test_fill_budget_codepicker_fails_when_popup_never_opens():
    """돋보기를 눌렀는데 팝업이 안 뜨면 하드 실패 — 잔여 팝업을 피커로 오독하는 사고 차단."""
    page = _PickerPage(opens=False)
    r = await steps.fill_budget_codepicker(page, _BG_COMBO)
    assert r["ok"] is False and "열리지 않" in r["reason"]


async def test_fill_budget_codepicker_warns_when_form_display_unreadable():
    """폼 표시값을 못 읽으면 warn + verified=False — '반영됨'으로 단정하지 않는다(soft)."""
    page = _PickerPage(display=None)
    r = await steps.fill_budget_codepicker(page, _BG_COMBO)
    assert r["ok"] is True and r["verified"] is False and r.get("warn")


# ── save_document 관찰 창(실시간) ──────────────────────────────────────────────
class _LateErrorSavePage(_OmniPage):
    """F7 후 **늦게**(5번째 폴) 오류 모달이 뜨는 fake — 관찰 창이 짧으면 성공으로 오판한다.

    실측 주석대로 F7 직후 모달까지 ~1-2s 걸린다. 관찰 창이 page.wait_for_timeout(명목) 기반이면
    delay_scale 0.15 에서 3s→450ms 로 줄어 이 모달을 못 본다 — 그래서 관찰 대기는 실시간
    프리미티브여야 하고, 이 테스트는 **관찰 루프가 wait_for_timeout 을 쓰지 않는지**도 본다.
    """

    def __init__(self, *, appear_on: int = 5):
        super().__init__()
        self.popups = []  # 카드팝업은 이미 닫힌 상태(저장 전제)
        self._appear_on = appear_on
        self.snaps = 0
        self.timeouts = 0
        self.modals: list[dict] = []

    async def wait_for_timeout(self, ms):
        if "F7" in self.keys:  # F7 이후 = 관찰 루프 구간(그 전은 잔여 모달 정리)
            self.timeouts += 1
        return None

    async def evaluate(self, script, arg=None):
        if script == js.MODALS_SNAPSHOT_JS:
            self.snaps += 1
            if self.snaps == self._appear_on:
                self.modals = [{"title": "오류", "text": "[승인번호: X] 승인 건 계정과 다릅니다."}]
            return list(self.modals)
        if script == js.VALIDATION_TOAST_JS:
            return []
        if script == js.MODAL_BTN_BOX_JS:
            return {"x": 61, "y": 61, "title": "오류"} if self.modals else None
        return await super().evaluate(script, arg)


async def test_save_document_observes_long_enough_to_catch_late_error_modal():
    """5번째 폴에 뜬 오류 모달을 잡아 저장 실패로 보고해야 한다(관찰 창 조기 종료 금지)."""
    page = _LateErrorSavePage(appear_on=5)
    r = await steps.save_document(page, confirm=True)
    assert r["ok"] is False and "승인 건 계정과 다릅니다" in r["reason"]
    assert page.snaps >= 5


async def test_save_document_observation_loop_does_not_use_scaled_wait():
    """관찰 대기가 page.wait_for_timeout 이면 delay_scale 로 창이 줄어든다 — 쓰지 않아야 한다."""
    page = _LateErrorSavePage(appear_on=99)  # 모달 없음 → 최소 관찰 창까지 폴링
    r = await steps.save_document(page, confirm=True)
    assert r["ok"] is True
    assert page.timeouts == 0, "관찰 루프가 delay_scale 대상 대기(wait_for_timeout)를 썼다"
    assert page.snaps >= int(steps._SAVE_MIN_OBSERVE_S / steps._SAVE_POLL_S)


# ── apply_rows_to_document 관찰 창(실시간) — 2026-08-07 감사 교정 회귀 ─────────────
class _StuckCardWinPage(_LateModalPage):
    """'적용' 후 카드팝업이 끝내 닫히지 않는 fake — 모달도 없다(서버 처리 장기화 흉내)."""

    def __init__(self):
        super().__init__(card_win=True)
        self._spawned = True  # 부모의 지연 모달 스폰 비활성화(모달 없음 유지)
        self.timeouts = 0

    async def wait_for_timeout(self, ms):
        self.timeouts += 1
        return None

    async def evaluate(self, script, arg=None):
        if script == js.MODALS_SNAPSHOT_JS:
            return []
        return await super().evaluate(script, arg)


async def test_apply_rows_to_document_cap_loop_does_not_use_scaled_wait():
    """미닫힘 관찰 루프가 wait_for_timeout(명목 카운터)을 쓰면 delay_scale 0.15 에서 45s
    상한이 ~12-20s 로 붕괴한다 — _real_sleep(실시간, 테스트에선 no-op) 폴이어야 한다."""
    page = _StuckCardWinPage()
    r = await steps.apply_rows_to_document(page, [0, 1])
    assert r["ok"] is False and "닫히지 않음" in r["reason"]
    assert page.timeouts == 0, "관찰 루프가 delay_scale 대상 대기(wait_for_timeout)를 썼다"
    # 명목 폴백 카운터로도 45s 상한(300폴)까지는 관찰했다(조기 소진 금지).
    assert r["elapsed_ms"] >= 0 and r["clicks"] == 0


# ── 공용 엔진 fill_codepicker — '적용' 미출현/미닫힘 가짜 성공 차단(2026-08-07 감사) ──
class _EnginePickerPage:
    """엔진 fill_codepicker fake — 팝업 open 상태로 오픈/선택/적용/닫힘 시맨틱을 지킨다."""

    def __init__(self, *, has_apply=True, closes=True):
        self._has_apply = has_apply
        self._closes = closes
        self.open = False
        self.clicks: list[tuple] = []
        self.close_calls = 0
        self.mouse = self

    async def click(self, x, y):
        self.clicks.append((x, y))
        if (x, y) == (51, 51):
            self.open = True  # 돋보기 → 팝업 오픈
        if (x, y) == (52, 52) and self._closes:
            self.open = False  # '적용' → 닫힘

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, script, arg=None):
        if "bg_cd-wrapper" in script:
            return {"x": 51, "y": 51}
        if script == js_lib.PICKER_ROWCOUNT_JS:
            return 1 if self.open else -1
        if script == js_lib.PICKER_READ_JS:
            return {"rows": 1, "options": [{"i": 0, "code": "2006", "name": "본사"}]}
        if script == js_lib.PICKER_SELECT_JS:
            return {"ok": True}
        if script == js_lib.PICKER_APPLY_BTN_JS:
            return {"x": 52, "y": 52} if self._has_apply else None
        if script == js_lib.PICKER_CLOSE_JS:
            self.close_calls += 1
            self.open = False
            return True
        return None


async def test_engine_fill_codepicker_ok_when_applied_and_closed():
    page = _EnginePickerPage()
    r = await steps.fill_codepicker(page, "bg_cd", "", "BG_CD", "BG_NM")
    assert r["ok"] is True and r["code"] == "2006"
    assert page.open is False  # 피커가 실제로 닫혔다


async def test_engine_fill_codepicker_fails_when_apply_button_missing(monkeypatch):
    """'적용' 버튼 미출현이면 선택이 폼에 안 붙는다 — 예전엔 무조건 {ok:True, code, name}."""
    from nbkit.omnisol import latency

    monkeypatch.setattr(latency, "budget_ms", lambda ms: 1)  # 폴 상한 축소(테스트 속도)
    page = _EnginePickerPage(has_apply=False)
    r = await steps.fill_codepicker(page, "bg_cd", "", "BG_CD", "BG_NM")
    assert r["ok"] is False and "적용" in r["reason"]
    assert page.close_calls >= 1 and page.open is False  # 실패 시 피커를 방치하지 않는다


async def test_engine_fill_codepicker_fails_when_picker_stays_open(monkeypatch):
    """'적용' 후에도 팝업이 남으면 하드 실패 — 다음 non-법인카드 k-window 조작 오염 차단."""
    from nbkit.omnisol import latency

    monkeypatch.setattr(latency, "budget_ms", lambda ms: 1)
    page = _EnginePickerPage(closes=False)
    r = await steps.fill_codepicker(page, "bg_cd", "", "BG_CD", "BG_NM")
    assert r["ok"] is False and "닫히지 않" in r["reason"]
    assert page.open is False  # _fail 경로가 잔존 팝업을 닫았다


# ── 공용 엔진 _open_picker — 버튼 출현 폴링 상한은 실시간(2026-08-07 감사) ─────────
class _SlowBtnPage:
    """코드피커 버튼이 41번째 폴에야 렌더되는 fake — 종전 명목 24폴 상한이면 미오픈 실패."""

    def __init__(self, appear_on: int = 41):
        self._appear_on = appear_on
        self.btn_polls = 0
        self.open = False
        self.mouse = self

    async def click(self, x, y):
        self.open = True

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, script, arg=None):
        if "bg_cd-wrapper" in script:
            self.btn_polls += 1
            return {"x": 1, "y": 2} if self.btn_polls >= self._appear_on else None
        if script == js_lib.PICKER_ROWCOUNT_JS:
            return 3 if self.open else -1
        return None


async def test_engine_open_picker_budget_is_realtime_not_poll_count():
    """실시간 예산(6s) 안이면 폴 횟수와 무관하게 오픈 성공 — delay_scale 0.15 에서 관찰창이
    24×37.5ms≈0.9s 로 붕괴하던 명목 카운터 회귀 방지(2026-07-10 prod 0건 사고 재발 차단)."""
    page = _SlowBtnPage(appear_on=41)  # 종전 range(24) 상한을 넘는 지연 출현
    assert await steps._open_picker(page, "bg_cd") is True
    assert page.btn_polls >= 41 and page.open is True
