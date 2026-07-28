"""expense_card.tools 단위테스트 — page 조작 도구 디스패치 + **반영 확인**(verify 커널).

`ErpFake` 는 카드상세 모달 + 코드피커 팝업의 **실물 시맨틱**을 지키는 최소 모형이다:
  · 카드상세 모달 자체가 `.k-window` 라 팝업 개수는 **1부터** 시작한다(감사에서 드러난
    "visible k-window 가 하나라도 있으면 열림" 판정이 항상 참이던 원인).
  · 돋보기를 눌러야 팝업이 뜨고, **'적용'을 눌러야** 폼 표시값이 바뀐다(안 누르면 안 붙는다).
  · 팝업은 '적용'/'닫기'로만 사라진다.
그래서 "세터가 ok 를 냈다"만으로는 테스트가 통과하지 않는다.

계약(각 도구 공통 3케이스):
  반영 성공 → ok / 반영 실패(값이 안 붙음·다름) → 하드 실패 / 리더가 못 읽음 → ok + warn.

저장(F7) 액션이 없음을 코드 경로로 확인한다(어떤 도구도 BTN_SAVE 를 클릭하지 않는다).
"""

from __future__ import annotations

from typing import Any, Callable

import app.agents.expense_card.tools as T
from nbkit.omnisol import js_lib


class _FakeKeyboard:
    def __init__(self) -> None:
        self.presses: list[str] = []

    async def press(self, key: str) -> None:
        self.presses.append(key)


class _RoutedMouse:
    """좌표 클릭을 ErpFake 의 핫스팟 동작으로 라우팅(고정 좌표 = 실제 버튼)."""

    def __init__(self, erp: "ErpFake") -> None:
        self._erp = erp
        self.clicks: list[tuple[int, int]] = []

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))
        self._erp.on_click(x, y)


class ErpFake:
    """카드상세 모달 + 코드피커 팝업의 최소 시맨틱 모형(Playwright Page 대역)."""

    PICKER_XY = {"프로젝트": (10, 20), "예산단위": (11, 21), "계정": (12, 22), "거래처": (13, 23)}
    APPLY_XY = (90, 90)
    QUERY_XY = (80, 80)
    CLOSE_XY = (70, 70)

    def __init__(
        self,
        *,
        form: dict[str, str] | None = None,
        picker_opens: bool = True,
        apply_present: bool = True,
        reflect: bool = True,
        search_ok: bool = True,
        keyword_ok: bool = True,
        popup_values: tuple[str, ...] = (),
        project_options: list[dict] | None = None,
        budget_read: dict | None = None,
        account_read: dict | None = None,
        extra_popups: int = 0,
        close_works: bool = True,
        readable: bool = True,
        input_transform: Callable[[str], str] | None = None,
    ) -> None:
        self.popups: list[str] = ["카드상세"] + ["잔여"] * extra_popups  # 모달이 첫 k-window
        self.form: dict[str, str] = dict(form or {})
        self.picker_opens = picker_opens
        self.apply_present = apply_present
        self.reflect = reflect  # False = '적용'해도 폼에 안 붙는다(조용한 실패 재현)
        self.search_ok = search_ok
        self.keyword_ok = keyword_ok
        self.popup_values = popup_values
        self.project_options = project_options or []
        self.budget_read = budget_read or {"n": 0, "dept": "", "rows": []}
        self.account_read = account_read or {"n": 0, "cols": [], "rows": []}
        self.close_works = close_works
        self.readable = readable  # False = 리더가 모달 필드를 못 읽음(확인 불가)
        self.input_transform = input_transform or (lambda v: v)
        self.pending: tuple[str, str] | None = None  # (필드, 선택값) — '적용' 때 폼에 붙는다
        self.selects: dict[str, str] = {}
        self.inputs: dict[str, str] = {}
        self.queries = 0

        self.mouse = _RoutedMouse(self)
        self.keyboard = _FakeKeyboard()

    # ── 화면 동작 ──────────────────────────────────────────────────────────────
    def on_click(self, x: int, y: int) -> None:
        for label, xy in self.PICKER_XY.items():
            if (x, y) == xy:
                if self.picker_opens and len(self.popups) == 1:
                    self.popups.append(label)
                    self.pending = None
                return
        if (x, y) == self.QUERY_XY:
            self.queries += 1
            return
        if (x, y) == self.CLOSE_XY:
            if self.close_works and len(self.popups) > 1:
                self.popups.pop()
            return
        if (x, y) == self.APPLY_XY:
            if len(self.popups) > 1:
                self.popups.pop()
                if self.reflect and self.pending:
                    self.form[self.pending[0]] = self.pending[1]
                self.pending = None

    # ── page 대역 ─────────────────────────────────────────────────────────────
    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    async def screenshot(self, **_kw: Any) -> bytes:
        return b"\xff\xd8\xff\xe0jpeg"

    async def evaluate(self, script: Any, arg: Any = None) -> Any:  # noqa: C901 — 라우팅 표
        top = self.popups[-1]
        if script is js_lib.POPUP_COUNT_JS:
            return len(self.popups)
        if script is T.MODAL_IDLE_JS:
            return True
        if script is T.CARD_PICKER_BOX_JS:
            xy = self.PICKER_XY.get(arg)
            return {"x": xy[0], "y": xy[1]} if xy else None
        if script is js_lib.PROJECT_PICKER_BOX_JS:
            xy = self.PICKER_XY["프로젝트"]
            return {"x": xy[0], "y": xy[1]}
        if script is js_lib.PROJECT_POPUP_OPEN_JS:
            return len(self.popups) > 1 and top == "프로젝트"
        if script in (T.CARD_POPUP_SEARCH_JS, js_lib.PROJECT_SEARCH_SET_JS):
            return self.search_ok
        if script is T.POPUP_SET_KEYWORD_JS:
            return self.keyword_ok
        if script is js_lib.PROJECT_READ_JS:
            return {"options": self.project_options}
        if script is js_lib.PROJECT_SELECT_JS:
            hit = next((o for o in self.project_options if o.get("value") == arg), None)
            if not hit:
                return {"ok": False}
            self.pending = ("프로젝트", hit.get("label") or arg)
            return {"ok": True, "name": hit.get("label")}
        if script is T.CARD_POPUP_SELECT_JS:
            if arg in self.popup_values:
                self.pending = (top, arg)
                return {"ok": True}
            return {"ok": False, "reason": "value-not-found"}
        if script in (T.CARD_POPUP_APPLY_BOX_JS, js_lib.PROJECT_APPLY_BOX_JS):
            return {"x": self.APPLY_XY[0], "y": self.APPLY_XY[1]} if self.apply_present else None
        if script is T.POPUP_QUERY_BTN_JS:
            return {"x": self.QUERY_XY[0], "y": self.QUERY_XY[1]}
        if script is T.POPUP_CLOSE_BTN_JS:
            return {"x": self.CLOSE_XY[0], "y": self.CLOSE_XY[1]}
        if script is T.BUDGET_READ_JS:
            return self.budget_read
        if script is T.BUDGET_SELECT_JS:
            row = next((r for r in (self.budget_read.get("rows") or []) if r["idx"] == arg), None)
            if not row:
                return {"ok": False, "reason": "row"}
            self.pending = ("예산단위", row["bg"])
            return {"ok": True}
        if script is T.ACCOUNT_READ_JS:
            return self.account_read
        if script is T.ACCOUNT_SELECT_JS:
            rows = self.account_read.get("rows") or []
            if arg >= len(rows):
                return {"ok": False, "reason": "row"}
            self.pending = ("계정", next(iter(rows[arg].values())))
            return {"ok": True}
        if script is T.CARD_DROPDOWN_SET_JS:
            label, value = arg
            sid = f"s_{label}"
            self.selects[f"#{sid}"] = value
            return {"ok": True, "text": value, "id": sid}
        if script is T.CARD_TEXT_SET_JS:
            label, value = arg
            iid = f"i_{label}"
            self.inputs[f"#{iid}"] = self.input_transform(value)
            return {"ok": True, "id": iid}
        if script is js_lib.SELECTED_TEXT_JS:
            if arg not in self.selects:
                return {"ok": False, "reason": "no-select"}
            return {"ok": True, "text": self.selects[arg], "value": self.selects[arg]}
        if script is js_lib.SCOPED_FIELD_VALUE_JS:
            if not self.readable:
                return None  # 리더가 스코프/필드를 못 찾음 = 확인 불가
            if arg.get("selector"):
                return self.inputs.get(arg["selector"])  # 없으면 None = 확인 불가
            return self.form.get(arg.get("label"))  # 없으면 None = 확인 불가
        return None


def _budget_rows(*rows: dict) -> dict:
    return {"n": len(rows), "dept": "인사기획팀", "rows": list(rows)}


_SEOK_JE = {"idx": 0, "bg": "인사기획팀", "biz": "b1", "acct": "(제)복리후생비-석식"}
_SEOK_PAN = {"idx": 1, "bg": "인사기획팀", "biz": "b2", "acct": "(판)복리후생비-석식"}


# ══════════════════════════════════════════════════════════════════════════════
# fill_dropdown — 세팅 ok 가 아니라 **선택값 재확인**이 성공 기준
# ══════════════════════════════════════════════════════════════════════════════
async def test_do_fill_dropdown_ok_when_selection_sticks():
    page = ErpFake()
    v = await T.do_fill_dropdown(page, "부가세구분", "공제")
    assert v.ok and v.warn is None
    assert "공제" in v.message and "반영 확인" in v.message


async def test_do_fill_dropdown_hard_fails_when_value_reverted():
    """change 핸들러가 값을 되돌리는 연쇄 필드 재현 — 세터는 ok 지만 선택값이 다르다."""

    class _Reverting(ErpFake):
        async def evaluate(self, script: Any, arg: Any = None) -> Any:
            if script is T.CARD_DROPDOWN_SET_JS:
                self.selects["#s_부가세구분"] = "불공제"  # 되돌려짐
                return {"ok": True, "text": "공제", "id": "s_부가세구분"}
            return await super().evaluate(script, arg)

    v = await T.do_fill_dropdown(_Reverting(), "부가세구분", "공제")
    assert not v.ok and v.status == "fail"
    assert "유지되지 않음" in v.message


async def test_do_fill_dropdown_warns_when_select_unreadable():
    """리더가 select 를 못 읽음 = 확인 불가 → 하드 실패가 아니라 warn 후 진행."""

    class _NoId(ErpFake):
        async def evaluate(self, script: Any, arg: Any = None) -> Any:
            if script is T.CARD_DROPDOWN_SET_JS:
                return {"ok": True, "text": "공제", "id": ""}  # select id 없음
            return await super().evaluate(script, arg)

    v = await T.do_fill_dropdown(_NoId(), "부가세구분", "공제")
    assert v.ok and v.warn
    assert "미확인" in v.message


async def test_do_fill_dropdown_fail_keeps_option_hint():
    class _NoSelect(ErpFake):
        async def evaluate(self, script: Any, arg: Any = None) -> Any:
            if script is T.CARD_DROPDOWN_SET_JS:
                return {"ok": False, "reason": "select-not-found"}
            return await super().evaluate(script, arg)

    v = await T.do_fill_dropdown(_NoSelect(), "부가세구분", "공제")
    assert not v.ok and "select-not-found" in v.message


# ══════════════════════════════════════════════════════════════════════════════
# fill_text — 입력값 readback(마스킹·날짜 재포맷 허용, 거부는 하드 실패)
# ══════════════════════════════════════════════════════════════════════════════
async def test_do_fill_text_ok_with_readback():
    page = ErpFake()
    v = await T.do_fill_text(page, "적요", "직원 야근 식대(법인카드)")
    assert v.ok and v.warn is None and "반영 확인" in v.message


async def test_do_fill_text_ok_when_widget_reformats_date():
    """날짜 위젯이 '20260707' → '2026-07-07' 로 재포맷해도 정상 입력이다(하드 실패 금지)."""
    page = ErpFake(input_transform=lambda v: f"{v[:4]}-{v[4:6]}-{v[6:]}" if v.isdigit() else v)
    v = await T.do_fill_text(page, "승인일", "20260707")
    assert v.ok and "반영 확인" in v.message


async def test_do_fill_text_hard_fails_when_input_rejected():
    """마스킹/검증이 입력을 거부해 빈 값이 되는 자리 — 예전엔 'ok(미검증)' 로 통과했다."""
    page = ErpFake(input_transform=lambda _v: "")
    v = await T.do_fill_text(page, "카드번호", "1234")
    assert not v.ok and v.status == "fail"
    assert "반영되지 않음" in v.message


async def test_do_fill_text_warns_when_value_unreadable():
    class _NoId(ErpFake):
        async def evaluate(self, script: Any, arg: Any = None) -> Any:
            if script is T.CARD_TEXT_SET_JS:
                return {"ok": True, "id": ""}  # id 없음 → 라벨 근접도 못 읽음
            return await super().evaluate(script, arg)

    v = await T.do_fill_text(_NoId(), "적요", "메모")
    assert v.ok and v.warn and "미확인" in v.message


# ══════════════════════════════════════════════════════════════════════════════
# close_top_popup — '닫혔는지' 확인(스테일 팝업이 다음 조작 root 가 되는 사고 차단)
# ══════════════════════════════════════════════════════════════════════════════
async def test_close_top_popup_noop_when_only_modal():
    page = ErpFake()
    v = await T.close_top_popup(page)
    assert v.ok and page.mouse.clicks == [] and page.keyboard.presses == []


async def test_close_top_popup_confirms_close():
    page = ErpFake(extra_popups=1)
    v = await T.close_top_popup(page)
    assert v.ok
    assert ErpFake.CLOSE_XY in page.mouse.clicks
    assert len(page.popups) == 1


async def test_close_top_popup_hard_fails_when_popup_stays():
    page = ErpFake(extra_popups=1, close_works=False)
    v = await T.close_top_popup(page)
    assert not v.ok and v.status == "fail"
    assert "닫히지 않" in v.message


# ══════════════════════════════════════════════════════════════════════════════
# fill_search(미검증 코드피커) — 팝업 개수 증가 / 검색창 / 적용 반영
# ══════════════════════════════════════════════════════════════════════════════
async def test_do_fill_search_unverified_ok_reflects_form():
    page = ErpFake(popup_values=("ACME",), form={"거래처": ""})
    v = await T.do_fill_search(page, "거래처", "", "ACME")
    assert v.ok and v.warn is None
    assert ErpFake.APPLY_XY in page.mouse.clicks
    assert page.form["거래처"] == "ACME"


async def test_do_fill_search_hard_fails_when_apply_not_reflected():
    """'적용'은 눌렀는데 폼에 안 붙는 대표 사고 — 반드시 하드 실패."""
    page = ErpFake(popup_values=("ACME",), form={"거래처": ""}, reflect=False)
    v = await T.do_fill_search(page, "거래처", "", "ACME")
    assert not v.ok and v.status == "fail"
    assert "반영되지 않음" in v.message


async def test_do_fill_search_hard_fails_when_apply_button_missing():
    """적용 버튼 좌표가 없으면 예전엔 클릭을 건너뛰고도 ok 였다 — 이제 명시적 실패."""
    page = ErpFake(popup_values=("ACME",), form={"거래처": ""}, apply_present=False)
    v = await T.do_fill_search(page, "거래처", "", "ACME")
    assert not v.ok and "'적용' 버튼을 찾지 못함" in v.message


async def test_do_fill_search_warns_when_display_unreadable():
    """리더가 모달 필드를 못 읽음(null) = 확인 불가 → warn 후 진행."""
    page = ErpFake(popup_values=("ACME",), readable=False)  # 리더가 null 반환
    v = await T.do_fill_search(page, "거래처", "", "ACME")
    assert v.ok and v.warn and "미확인" in v.message


async def test_do_fill_search_hard_fails_when_picker_does_not_open():
    """카드 모달 자체가 .k-window 라 '팝업 존재'는 항상 참이었다 — 개수 증가로 판정한다."""
    page = ErpFake(popup_values=("ACME",), picker_opens=False)
    v = await T.do_fill_search(page, "거래처", "", "ACME")
    assert not v.ok and "팝업이 열리지 않음" in v.message


async def test_do_fill_search_hard_fails_when_search_box_missing():
    """검색창을 못 찾으면 미필터 전체 목록이 후보가 된다 — 세터 bool 을 버리지 않는다."""
    page = ErpFake(popup_values=("ACME",), search_ok=False)
    v = await T.do_fill_search(page, "거래처", "에이스", "ACME")
    assert not v.ok and "검색창을 찾지 못함" in v.message


async def test_do_fill_search_missing_button_marks_scaffold():
    page = ErpFake()
    v = await T.do_fill_search(page, "사용자", "", "홍길동")  # PICKER_XY 에 없는 라벨
    assert not v.ok and "미검증" in v.message and "코드피커 버튼" in v.message


async def test_do_fill_search_row_not_found_is_hard_fail():
    page = ErpFake(popup_values=("OTHER",))
    v = await T.do_fill_search(page, "거래처", "", "ACME")
    assert not v.ok and "선택 실패" in v.message


# ── fill_search(프로젝트, 검증 경로) ──────────────────────────────────────────
_PJT = [{"label": "SPARES_ACM", "value": "W1", "description": "스페어"}]


async def test_do_fill_search_project_uses_verified_js_and_confirms():
    class _Guard(ErpFake):
        async def evaluate(self, script: Any, arg: Any = None) -> Any:
            if script is T.CARD_PICKER_BOX_JS:
                raise AssertionError("프로젝트는 미검증 CARD_PICKER_BOX_JS 를 쓰면 안 됨")
            return await super().evaluate(script, arg)

    page = _Guard(project_options=_PJT, form={"프로젝트": ""})
    v = await T.do_fill_search(page, "프로젝트", "SPARES", "SPARES_ACM")
    assert v.ok and "미검증" not in v.message
    assert page.form["프로젝트"] == "SPARES_ACM"


async def test_do_fill_search_project_hard_fails_when_not_reflected():
    page = ErpFake(project_options=_PJT, form={"프로젝트": ""}, reflect=False)
    v = await T.do_fill_search(page, "프로젝트", "SPARES", "SPARES_ACM")
    assert not v.ok and "반영되지 않음" in v.message


async def test_do_fill_search_project_no_result_is_fail():
    page = ErpFake(project_options=[], form={"프로젝트": ""})
    v = await T.do_fill_search(page, "프로젝트", "ZZZ", "ZZZ")
    assert not v.ok and "일치하는 결과가 없음" in v.message


async def test_do_fill_search_project_ambiguous_asks():
    opts = [
        {"label": "SPARES_ACM_A", "value": "W1", "description": ""},
        {"label": "SPARES_ACM_B", "value": "W2", "description": ""},
    ]
    page = ErpFake(project_options=opts, form={"프로젝트": ""})
    v = await T.do_fill_search(page, "프로젝트", "SPARES", "SPARES_ACM")
    assert not v.ok and v.status == "ambiguous"


# ══════════════════════════════════════════════════════════════════════════════
# budget(예산단위) — unsupported / ambiguous / ok / 반영 실패
# ══════════════════════════════════════════════════════════════════════════════
async def test_do_budget_unsupported_no_page_calls():
    class _Boom(ErpFake):
        async def evaluate(self, script: Any, arg: Any = None) -> Any:
            raise AssertionError("unsupported 항목은 page 를 건드리면 안 됨")

    v = await T.do_budget(_Boom(), "택시비", "")
    assert v.status == "unsupported" and not v.ok
    assert "택시비" in v.message


async def test_do_budget_ambiguous_asks_je_pan():
    page = ErpFake(budget_read=_budget_rows(_SEOK_JE, _SEOK_PAN), form={"예산단위": ""})
    v = await T.do_budget(page, "야근식대", "")
    assert v.status == "ambiguous" and not v.ok
    assert "제조/판매" in v.message
    assert len(page.popups) == 1  # 되묻기 전에 팝업을 닫아 다음 시도가 스테일 창을 안 쓰게


async def test_do_budget_ok_selects_and_confirms_form():
    page = ErpFake(budget_read=_budget_rows(_SEOK_JE), form={"예산단위": ""})
    v = await T.do_budget(page, "야근식대", "제조")
    assert v.ok and v.warn is None
    assert "복리후생비-석식" in v.message and "반영 확인" in v.message
    assert ErpFake.APPLY_XY in page.mouse.clicks
    assert page.form["예산단위"] == "인사기획팀"


async def test_do_budget_hard_fails_when_not_reflected():
    page = ErpFake(budget_read=_budget_rows(_SEOK_JE), form={"예산단위": ""}, reflect=False)
    v = await T.do_budget(page, "야근식대", "제조")
    assert not v.ok and v.status == "fail" and "적용 실패" in v.message


async def test_do_budget_warns_when_display_unreadable():
    page = ErpFake(budget_read=_budget_rows(_SEOK_JE), readable=False)  # 리더가 null 반환
    v = await T.do_budget(page, "야근식대", "제조")
    assert v.ok and v.warn and "반영 미확인" in v.message


async def test_do_budget_hard_fails_when_keyword_box_missing():
    """#keyword 를 못 찾으면 **미필터 전체 목록**이 후보가 된다 — 조용히 통과시키지 않는다."""
    page = ErpFake(budget_read=_budget_rows(_SEOK_JE), keyword_ok=False)
    v = await T.do_budget(page, "야근식대", "제조")
    assert not v.ok and "검색창" in v.message
    assert len(page.popups) == 1  # 중단하며 팝업을 닫는다


async def test_do_budget_no_match_is_fail_and_closes_popup():
    page = ErpFake(budget_read=_budget_rows({"idx": 0, "bg": "타부서", "biz": "b", "acct": "(제)소모품비"}))
    v = await T.do_budget(page, "야근식대", "")
    assert not v.ok and "못 찾음" in v.message
    assert len(page.popups) == 1


# ══════════════════════════════════════════════════════════════════════════════
# account(계정 자동선택)
# ══════════════════════════════════════════════════════════════════════════════
_ACCT_1 = {"n": 1, "cols": ["ACCT_NM"], "rows": [{"ACCT_NM": "복리후생비-석식"}]}
_ACCT_2 = {"n": 2, "cols": ["ACCT_NM"], "rows": [{"ACCT_NM": "복리후생비-석식"}, {"ACCT_NM": "소모품비"}]}


async def test_do_account_ok_autoselect_and_confirms():
    page = ErpFake(account_read=_ACCT_1, form={"계정": ""})
    v = await T.do_account(page)
    assert v.ok and v.warn is None
    assert "복리후생비-석식" in v.message and "반영 확인" in v.message
    assert page.form["계정"] == "복리후생비-석식"


async def test_do_account_warns_when_multiple_candidates():
    """2건 이상이어도 첫 행을 고르지만 그 모호성을 warn 으로 노출한다."""
    page = ErpFake(account_read=_ACCT_2, form={"계정": ""})
    v = await T.do_account(page)
    assert v.ok and v.warn and "2건" in v.warn


async def test_do_account_hard_fails_when_not_reflected():
    page = ErpFake(account_read=_ACCT_1, form={"계정": ""}, reflect=False)
    v = await T.do_account(page)
    assert not v.ok and "적용 실패" in v.message


async def test_do_account_no_rows_is_fail_and_closes_popup():
    page = ErpFake(account_read={"n": 0, "cols": [], "rows": []})
    v = await T.do_account(page)
    assert not v.ok and "후보가 없음" in v.message
    assert len(page.popups) == 1


async def test_do_account_hard_fails_when_picker_does_not_open():
    page = ErpFake(account_read=_ACCT_1, picker_opens=False)
    v = await T.do_account(page)
    assert not v.ok and "팝업이 열리지 않음" in v.message


# ══════════════════════════════════════════════════════════════════════════════
# 절대 안전 — 저장(F7)/삭제(F6)/상신 액션을 어디서도 만들지 않는다
# ══════════════════════════════════════════════════════════════════════════════
def test_tools_module_has_no_save_or_submit_action():
    with open(T.__file__, encoding="utf-8") as fp:
        src = fp.read()
    # 경고 주석에는 'F7'·'상신'이 나오므로 **액션 형태**(셀렉터·키 입력)만 금지한다.
    for banned in ("BTN_SAVE", "main-button.save", 'press("F7")', "press('F7')", 'press("F6")'):
        assert banned not in src, f"저장·상신·삭제 액션 흔적: {banned}"
