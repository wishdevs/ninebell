"""출장(국내/자차) steps 순수 로직 + dump_partners 페이징 단위 테스트.

브라우저 없이: 정확매칭 우선순위(거래처/예산/프로젝트), cost_type→BGACCT 규칙, 거래처
덤프 dedupe, dump_partners 끝행+ArrowDown 페이징 루프(가짜 page)를 검증한다.
"""

from __future__ import annotations

import pytest

from app.agents.trip_domestic import steps
from nbkit.omnisol import js_lib


# ── cost_type → 예산계정명 ────────────────────────────────────────────────────
def test_bgacct_name_for_cost_type():
    assert steps.bgacct_name_for_cost_type("판관비") == "(판)여비교통비-국내출장"
    assert steps.bgacct_name_for_cost_type("제조원가") == "(제)여비교통비-국내출장"


@pytest.mark.parametrize("bad", [None, "", "기타", "판관"])
def test_bgacct_name_rejects_unknown_cost_type(bad):
    with pytest.raises(ValueError, match="비용구분"):
        steps.bgacct_name_for_cost_type(bad)


# ── 거래처 정확매칭 우선순위 ──────────────────────────────────────────────────
_TOLL_OPTS = [
    {"i": 0, "PARTNER_CD": "10512", "PARTNER_NM": "한국도로공사", "BIZR_NO": "1298200103"},
    {"i": 1, "PARTNER_CD": "10750", "PARTNER_NM": "한국도로공사안성(부산)주유소", "BIZR_NO": "1258211307"},
    {"i": 2, "PARTNER_CD": "15708", "PARTNER_NM": "한국도로공사문경(양평방향)주유소", "BIZR_NO": "5118205971"},
]


def test_pick_partner_exact_name_ignores_substring_matches():
    """부분포함(주유소)이 아니라 PARTNER_NM 완전일치만 — 통행료 공공기관 단건 확정."""
    row, err = steps.pick_partner_row(_TOLL_OPTS, "한국도로공사", code="10512")
    assert err is None
    assert row["PARTNER_CD"] == "10512"


def test_pick_partner_code_preferred_among_exact():
    """완전일치 다건이면 코드로 특정(카탈로그 코드 신뢰)."""
    opts = [
        {"i": 0, "PARTNER_CD": "A", "PARTNER_NM": "이트라이브2"},
        {"i": 1, "PARTNER_CD": "B", "PARTNER_NM": "이트라이브2"},
    ]
    row, err = steps.pick_partner_row(opts, "이트라이브2", code="B")
    assert err is None and row["PARTNER_CD"] == "B"


def test_pick_partner_no_match_returns_error():
    row, err = steps.pick_partner_row(_TOLL_OPTS, "존재하지않는거래처", code=None)
    assert row is None and "일치 없음" in err


def test_pick_partner_ambiguous_without_code_errors():
    """완전일치가 서로 다른 코드로 다건인데 코드 미지정 → 모호 오류(임의선택 금지)."""
    opts = [
        {"i": 0, "PARTNER_CD": "A", "PARTNER_NM": "이트라이브2"},
        {"i": 1, "PARTNER_CD": "B", "PARTNER_NM": "이트라이브2"},
    ]
    row, err = steps.pick_partner_row(opts, "이트라이브2", code=None)
    assert row is None and "여러 건" in err


def test_pick_partner_self_search_single():
    """본인이름 검색 단건(코드 없이도 단일 코드로 수렴하면 선택)."""
    opts = [{"i": 0, "PARTNER_CD": "2026032511", "PARTNER_NM": "이트라이브2"}]
    row, err = steps.pick_partner_row(opts, "이트라이브2", code=None)
    assert err is None and row["PARTNER_CD"] == "2026032511"


# ── 예산단위 조합 정확매칭 ────────────────────────────────────────────────────
_BUDGET_OPTS = [
    {"i": 0, "BG_CD": "2005", "BG_NM": "회계팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
    {"i": 1, "BG_CD": "2005", "BG_NM": "회계팀", "BIZPLAN_NM": "운영비 (제조)", "BGACCT_NM": "(제)여비교통비-국내출장"},
    {"i": 2, "BG_CD": "2003", "BG_NM": "구매팀", "BIZPLAN_NM": "운영비 (제조)", "BGACCT_NM": "(제)여비교통비-국내출장"},
]


def test_pick_budget_department_and_cost_type_single():
    row, err = steps.pick_budget_row(_BUDGET_OPTS, "회계팀", "(판)여비교통비-국내출장")
    assert err is None and row["BG_CD"] == "2005" and row["BGACCT_NM"] == "(판)여비교통비-국내출장"


def test_pick_budget_department_ignores_separators():
    # user.department '인사/기획팀' 은 BG_NM '인사기획팀' 과 매칭돼야 한다(구분기호 무시).
    # _norm 이 공백만 제거해 '/'가 남아 무매칭되던 실측 버그(2026-07-06 스모크 검출) 회귀 방지.
    opts = [
        {"i": 0, "BG_CD": "2010", "BG_NM": "인사기획팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
        {"i": 1, "BG_CD": "2005", "BG_NM": "회계팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
    ]
    row, err = steps.pick_budget_row(opts, "인사/기획팀", "(판)여비교통비-국내출장")
    assert err is None and row["BG_CD"] == "2010"


def test_pick_budget_no_match_errors():
    row, err = steps.pick_budget_row(_BUDGET_OPTS, "없는팀", "(판)여비교통비-국내출장")
    assert row is None and "무매칭" in err


def test_pick_budget_multi_code_ambiguous():
    opts = [
        {"i": 0, "BG_CD": "2005", "BG_NM": "회계팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
        {"i": 1, "BG_CD": "9999", "BG_NM": "회계팀", "BIZPLAN_NM": "별도", "BGACCT_NM": "(판)여비교통비-국내출장"},
    ]
    row, err = steps.pick_budget_row(opts, "회계팀", "(판)여비교통비-국내출장")
    assert row is None and "다중매칭" in err


# ── 프로젝트 WBS 우선 / PJT_NM 폴백 ───────────────────────────────────────────
_PROJECT_OPTS = [
    {"i": 0, "PJT_NO": "PJ1", "PJT_NM": "알파", "WBS_NO": "W1"},
    {"i": 1, "PJT_NO": "PJ1", "PJT_NM": "알파", "WBS_NO": "W2"},
]


def test_pick_project_wbs_exact():
    row, err = steps.pick_project_row(_PROJECT_OPTS, "알파", "W2")
    assert err is None and row["WBS_NO"] == "W2"


def test_pick_project_falls_back_to_pjt_nm():
    row, err = steps.pick_project_row(_PROJECT_OPTS, "알파", "W9")  # WBS 무매칭 → 이름 폴백
    assert err is None and row["PJT_NM"] == "알파"


def test_pick_project_no_match_errors():
    row, err = steps.pick_project_row(_PROJECT_OPTS, "감마", None)
    assert row is None and "무매칭" in err


# ── 거래처 덤프 dedupe ────────────────────────────────────────────────────────
def test_partner_options_to_rows_dedupes_and_maps_bizno():
    opts = [
        {"PARTNER_CD": "10512", "PARTNER_NM": "한국도로공사", "BIZR_NO": "1298200103"},
        {"PARTNER_CD": "10512", "PARTNER_NM": "한국도로공사", "BIZR_NO": "1298200103"},  # 중복
        {"PARTNER_CD": "00037", "PARTNER_NM": "전준현", "BIZR_NO": None},
        {"PARTNER_CD": None, "PARTNER_NM": "코드없음"},  # 코드 없으면 제외
    ]
    rows = steps.partner_options_to_rows(opts)
    assert [r["code"] for r in rows] == ["10512", "00037"]
    assert rows[0]["bizNo"] == "1298200103"
    assert rows[1]["bizNo"] == ""  # None → ""


# ── dump_partners 페이징 루프(가짜 page) ──────────────────────────────────────
class _FakeKeyboard:
    async def press(self, key, delay=None):  # noqa: ANN001
        return None


class _PartnerMouse:
    """코드피커 버튼 클릭 → 팝업이 실제로 열린다(개수 0→1)."""

    def __init__(self, page) -> None:  # noqa: ANN001
        self._p = page

    async def click(self, x, y):  # noqa: ANN001
        self._p.popups = 1


class _FakePartnerPage:
    """dump_partners 의 evaluate 호출을 JS 식별로 디스패치하는 최소 가짜 page.

    rowcount 를 상수로 고정해 '증가 없음 → 3회 stable → 종료' 경로를 태운다. 팝업 개수는
    실제 상태로 들고 있어 오픈(0→1)·클로즈(1→0) 확인이 가짜 통과가 되지 않게 한다.
    """

    def __init__(self, rowcount: int, options: list[dict]) -> None:
        self._rowcount = rowcount
        self._options = options
        self.keyboard = _FakeKeyboard()
        self.mouse = _PartnerMouse(self)
        self.popups = 0
        self.closed = False
        self.read_calls = 0

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.PICKER_ROWCOUNT_JS:
            return self._rowcount if self.popups else -1
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self.popups
        if jsstr is js_lib.PICKER_SEARCH_JS:
            return {"ok": True, "field": "customTextBox"}
        if jsstr is js_lib.PICKER_FOCUS_LAST_JS:
            return {"ok": True, "row": self._rowcount - 1}
        if jsstr is js_lib.PICKER_READ_MULTI_JS:
            self.read_calls += 1
            return {"rows": self._rowcount, "options": self._options}
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.closed = True
            self.popups = 0
            return True
        # picker_btn_js(field) 는 동적 f-string(코드피커 버튼 좌표) → 버튼 좌표 반환.
        if "dews-codepicker-button" in jsstr:
            return {"x": 10, "y": 10}
        return None


# ── 예산 부서 부분포함 폴백(완전일치 없을 때 단건만) ──────────────────────────
def test_pick_budget_partial_containment_single():
    # 완전일치 부서 없음 + 부분포함 단건 → 채택(로그 남김). '인사기획팀' ⊂ '인사기획팀본부'.
    opts = [
        {"i": 0, "BG_CD": "2010", "BG_NM": "인사기획팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
        {"i": 1, "BG_CD": "2005", "BG_NM": "회계팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
    ]
    row, err = steps.pick_budget_row(opts, "인사기획팀본부", "(판)여비교통비-국내출장")
    assert err is None and row["BG_CD"] == "2010"


def test_pick_budget_partial_containment_multi_ambiguous():
    # 부분포함이 서로 다른 BG_CD 다건 → 임의선택 금지, 후보 나열 실패.
    opts = [
        {"i": 0, "BG_CD": "2010", "BG_NM": "인사팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
        {"i": 1, "BG_CD": "2011", "BG_NM": "인사기획팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
    ]
    row, err = steps.pick_budget_row(opts, "인사", "(판)여비교통비-국내출장")
    assert row is None and "부분포함 다중" in err


# ── set_transaction_amount 반영 금액 검증(거래금액 SPPRC_AMT2 primary) ─────────
class _AmountPage:
    """모든 금액 필드에 대해 같은 after 를 반환하는 최소 가짜 page."""

    def __init__(self, after: str) -> None:
        self._after = after
        self.fields: list = []

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if isinstance(arg, dict) and "field" in arg:
            self.fields.append(arg["field"])
        return {"ok": True, "after": self._after, "display": self._after}


async def test_set_transaction_amount_sets_txn_supply_total():
    page = _AmountPage("15400")
    r = await steps.set_transaction_amount(page, 15400)
    assert r["ok"] is True
    # 거래금액(SPPRC_AMT2) primary + 공급가액(SPPRC_AMT) + 합계(TOTAL_AMT) 세팅.
    assert page.fields == ["SPPRC_AMT2", "SPPRC_AMT", "TOTAL_AMT"]


async def test_set_transaction_amount_comma_stripped_match():
    r = await steps.set_transaction_amount(_AmountPage("15,400"), 15400)
    assert r["ok"] is True


async def test_set_transaction_amount_mismatch_fails():
    r = await steps.set_transaction_amount(_AmountPage("999"), 15400)
    assert r["ok"] is False and "반영 불일치" in r["reason"] and "거래금액" in r["reason"]


async def test_set_master_total_match():
    r = await steps.set_master_total(_AmountPage("44967"), 44967)
    assert r["ok"] is True


async def test_set_master_total_mismatch_fails():
    r = await steps.set_master_total(_AmountPage("0"), 44967)
    assert r["ok"] is False and "마스터 합계 반영 불일치" in r["reason"]


# ── set_invoice_date ((세금)계산서일 = START_DT 세팅·검증) ──────────────────────
class _DatePage:
    """START_DT setValue + READ_DETAIL_DATE_JS(compact) 검증용 가짜 page.

    실 ERP 날짜 셀 getValue 는 Date 객체 → READ_DETAIL_DATE_JS 가 브라우저 로컬 Y/M/D compact 로
    정규화한다. read_compact = 그 정규화 결과(모사). SET 은 field 기록.
    """

    def __init__(self, read_compact: str) -> None:
        self._read = read_compact
        self.fields: list = []

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if arg == "START_DT":  # READ_DETAIL_DATE_JS
            return {"ok": True, "compact": self._read, "raw": "Tue Jul 07 2026 00:00:00 GMT+0900"}
        if isinstance(arg, dict) and arg.get("field") == "START_DT":  # SET_DETAIL_CELL_JS
            self.fields.append(arg["field"])
            return {"ok": True, "after": arg["value"], "display": ""}
        return {"ok": True}


async def test_set_invoice_date_match():
    page = _DatePage("20260703")
    r = await steps.set_invoice_date(page, "20260703")
    assert r["ok"] is True
    assert page.fields == ["START_DT"]


async def test_set_invoice_date_date_object_normalized_match():
    # 실 ERP 는 Date 객체(String→'Tue Jul 07 2026 ...')를 반환 → 전용 리드가 compact 로 정규화해 통과.
    r = await steps.set_invoice_date(_DatePage("20260703"), "20260703")
    assert r["ok"] is True


async def test_set_invoice_date_mismatch_fails():
    r = await steps.set_invoice_date(_DatePage("20260704"), "20260703")
    assert r["ok"] is False and "계산서일 반영 불일치" in r["reason"]


async def test_set_invoice_date_bad_format_fails():
    r = await steps.set_invoice_date(_DatePage("20260703"), "2026-07-03")
    assert r["ok"] is False and "형식 오류" in r["reason"]


# ── set_counter_partner (상대계정 = BFC_PARTNER_CD 직접 setValue) ──────────────
async def test_set_counter_partner_match():
    r = await steps.set_counter_partner(_AmountPage("2026032511"), "2026032511")
    assert r["ok"] is True and r["after"] == "2026032511"


async def test_set_counter_partner_mismatch_fails():
    r = await steps.set_counter_partner(_AmountPage("0"), "2026032511")
    assert r["ok"] is False and "상대계정거래처 반영 불일치" in r["reason"]


# ── _select_and_apply: 적용버튼·셀반영·팝업닫힘 검증 ───────────────────────────
from app.agents.trip_domestic import js as trip_js  # noqa: E402


class _ApplyMouse:
    """'적용' 실클릭 — 실물처럼 클릭이 먹으면 셀에 값이 붙고 팝업이 닫힌다."""

    def __init__(self, page) -> None:  # noqa: ANN001
        self._p = page

    async def click(self, x, y):  # noqa: ANN001
        self._p.apply_clicks += 1
        if self._p.applies_at is not None and self._p.apply_clicks >= self._p.applies_at:
            self._p.cell = self._p.target_cell
            if self._p.gone:
                self._p.popups = 0


class _ApplyPage:
    """_select_and_apply 의 evaluate 를 JS 식별로 디스패치하는 가짜 page.

    실물 시맨틱: 시작 시 피커 팝업이 **1개 열려 있고**(POPUP_COUNT_JS=1), '적용' 클릭이 먹으면
    detail 셀에 값이 붙고 팝업이 닫힌다(개수 1→0). 확인은 셀 재독(GRID_CELL_VALUE_JS)과
    팝업 개수 감소 두 가지로만 하며, 둘 다 가짜가 아니라 상태 변화의 결과다.

    - applies_at=None : 몇 번을 눌러도 셀이 안 붙는다(적용 미반영).
    - applies_at=2    : 첫 클릭은 튕기고 **재클릭(reapply)** 에서만 붙는다.
    - cell_readable=False : 그리드를 못 읽는 세션(확인 불가) 모사.
    """

    def __init__(
        self,
        *,
        apply_box,
        cell_value: str,
        gone: bool = True,
        applies_at: int | None = 1,
        cell_readable: bool = True,
    ) -> None:
        self._apply_box = apply_box
        self.target_cell = cell_value
        self.cell = ""
        self.gone = gone
        self.applies_at = applies_at
        self._readable = cell_readable
        self.apply_clicks = 0
        self.popups = 1
        self.mouse = _ApplyMouse(self)
        self.closed = False

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.PICKER_SELECT_JS:
            return {"ok": True}
        if jsstr is js_lib.PICKER_APPLY_BTN_JS:
            return self._apply_box
        if jsstr is js_lib.GRID_CELL_VALUE_JS:
            if not self._readable:
                return {"ok": False, "reason": "detail 행 없음"}
            f = arg["field"]
            return {"ok": True, "row": 0, "rows": 1, "raw": {f: self.cell}, "compact": {f: ""}, "display": {f: None}}
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self.popups
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.closed = True
            self.popups = 0
            return True
        return None


async def test_select_and_apply_success():
    page = _ApplyPage(apply_box={"x": 1, "y": 1}, cell_value="한국도로공사")
    r = await steps._select_and_apply(page, 0, "거래처", "PARTNER_NM", "한국도로공사")
    assert r["ok"] is True and "warn" not in r
    assert page.closed is False  # 성공 경로는 명시 닫기를 하지 않는다(적용이 닫는다).


async def test_select_and_apply_missing_apply_button_fails():
    page = _ApplyPage(apply_box=None, cell_value="한국도로공사")
    r = await steps._select_and_apply(page, 0, "거래처", "PARTNER_NM", "한국도로공사")
    assert r["ok"] is False and "적용" in r["reason"] and page.closed is True


async def test_select_and_apply_cell_not_reflected_fails():
    # 셀을 읽을 수는 있는데 값이 안 붙음 = **하드 실패**(대상 데이터를 정의하는 값).
    page = _ApplyPage(apply_box={"x": 1, "y": 1}, cell_value="인사기획팀", applies_at=None)
    r = await steps._select_and_apply(page, 0, "예산단위", "BG_NM", "인사기획팀")
    assert r["ok"] is False and "미반영" in r["reason"] and page.closed is True


async def test_select_and_apply_reclicks_apply_when_first_click_bounces():
    # 첫 '적용'이 튕겨나간 경우 — 기다리기만 하면 영영 안 붙는다. reapply 로 재클릭해 살린다.
    page = _ApplyPage(apply_box={"x": 1, "y": 1}, cell_value="포장개선", applies_at=2)
    r = await steps._select_and_apply(page, 0, "프로젝트", "PJT_NM", "포장개선")
    assert r["ok"] is True and page.apply_clicks >= 2


async def test_select_and_apply_cell_unreadable_warns_and_proceeds():
    # 리더가 그리드를 못 읽음 = 확인 불가 → 하드 실패 금지, warn 을 달고 진행(D7 규율).
    page = _ApplyPage(apply_box={"x": 1, "y": 1}, cell_value="한국도로공사", cell_readable=False)
    r = await steps._select_and_apply(page, 0, "거래처", "PARTNER_NM", "한국도로공사")
    assert r["ok"] is True and "확인 불가" in r["warn"]


async def test_select_and_apply_popup_not_closed_fails():
    # 셀은 붙었는데 팝업이 안 닫힘 — 잔존 팝업은 F7 을 삼키므로 하드 실패로 승격한다.
    page = _ApplyPage(apply_box={"x": 1, "y": 1}, cell_value="포장개선", gone=False)
    r = await steps._select_and_apply(page, 0, "프로젝트", "PJT_NM", "포장개선")
    assert r["ok"] is False and "닫히지 않" in r["reason"]


async def test_dump_partners_pages_then_reads_and_dedupes():
    opts = [
        {"PARTNER_CD": "10512", "PARTNER_NM": "한국도로공사", "BIZR_NO": "1298200103"},
        {"PARTNER_CD": "00037", "PARTNER_NM": "전준현", "BIZR_NO": None},
        {"PARTNER_CD": "10512", "PARTNER_NM": "한국도로공사", "BIZR_NO": "1298200103"},  # 중복
    ]
    page = _FakePartnerPage(rowcount=3, options=opts)
    rows = await steps.dump_partners(page, max_rounds=5)
    assert page.closed is True  # 종료 시 팝업 닫힘.
    assert page.read_calls == 1  # 페이징 종료 후 1회 전량 읽기.
    assert [r["code"] for r in rows] == ["10512", "00037"]
    assert rows[0]["bizNo"] == "1298200103"


# ══════════════════════════════════════════════════════════════════════════════
# 확인 커널 적용 계약 — 반영 성공 / 반영 실패(하드) / 리더 미독(확인 불가 → warn)
# ══════════════════════════════════════════════════════════════════════════════
class _NotePage:
    """적요(NOTE_DC) setValue + 셀 재독 대조용 가짜 page.

    실물 시맨틱: `SET_DETAIL_CELL_JS` 는 **호출이 끝났다**만 알려주고(반영 보장 아님),
    실제 반영 여부는 `GRID_CELL_VALUE_JS` 재독으로만 알 수 있다. stored=None 이면 세팅이
    그대로 반영된 정상 셀, 문자열이면 그 값이 셀에 남아 있는 상태(미반영/이전 행 잔존).
    """

    def __init__(self, *, stored: str | None = None, readable: bool = True) -> None:
        self._stored = stored
        self._readable = readable
        self.cell = ""
        self.set_calls: list = []

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is trip_js.SET_DETAIL_CELL_JS:
            self.set_calls.append(arg)
            self.cell = arg["value"] if self._stored is None else self._stored
            return {"ok": True, "after": arg["value"], "display": ""}
        if jsstr is js_lib.GRID_CELL_VALUE_JS:
            if not self._readable:
                return {"ok": False, "reason": "detail 행 없음"}
            f = arg["field"]
            return {
                "ok": True, "row": 0, "rows": 1,
                "raw": {f: self.cell}, "compact": {f: ""}, "display": {f: None},
            }
        return None


async def test_set_row_note_reflected_ok():
    page = _NotePage()
    r = await steps.set_row_note(page, "통행료(현금) 2026-07-03")
    assert r["ok"] is True and r["after"] == "통행료(현금) 2026-07-03"
    assert page.set_calls == [{"field": "NOTE_DC", "value": "통행료(현금) 2026-07-03"}]


async def test_set_row_note_empty_text_is_verified_too():
    # 빈 적요도 '비어 있음'을 확인해야 통과한다(세터 ok 만 보고 넘어가지 않는다).
    r = await steps.set_row_note(_NotePage(), "")
    assert r["ok"] is True


async def test_set_row_note_not_reflected_fails_hard():
    # setValue 는 ok 를 냈는데 셀에는 이전 행 값이 남아 있는 상태 = 하드 실패(잘못된 적요 저장 방지).
    page = _NotePage(stored="앞 행 적요")
    r = await steps.set_row_note(page, "유류비 지원")
    assert r["ok"] is False and "적요 반영 불일치" in r["reason"]


async def test_set_row_note_unreadable_grid_warns_and_passes():
    # 리더가 그리드를 못 읽음 = 확인 불가 → 하드 실패 금지, warn 을 달고 진행.
    r = await steps.set_row_note(_NotePage(readable=False), "유류비 지원")
    assert r["ok"] is True and "확인 불가" in r["warn"]


# ── delete_blank_row: F6 사전 게이트(파괴적 액션) ──────────────────────────────
class _DeleteMouse:
    """삭제 버튼(9,9) 클릭은 **현재 행**을 지운다 — 실 ERP 와 같은 규칙."""

    def __init__(self, page) -> None:  # noqa: ANN001
        self._p = page

    async def click(self, x, y):  # noqa: ANN001
        self._p.clicks.append((x, y))
        if (x, y) == (9, 9) and self._p.delete_effective:
            self._p.deleted.append(self._p.current)
            self._p.rows.pop(self._p.current)


class _DeletePage:
    """delete_blank_row 용 가짜 page — detail 행 상태와 '현재 행'을 실제로 들고 있다.

    실물 시맨틱: 빈 행 선택은 **좌표 추정 클릭**이라 빗나갈 수 있다 → `current` 는 클릭이
    실제로 고른 행이며, 테스트는 그것이 의도한 빈 행과 다른 경우(데이터 행 위험)를 모사한다.
    """

    def __init__(
        self, *, rows: list[str], current: int, current_ok: bool = True,
        delete_btn: bool = True, delete_effective: bool = True,
    ) -> None:
        self.rows = list(rows)  # 각 원소 = PARTNER_NM('' 이면 빈 행)
        self.current = current
        self.current_ok = current_ok
        self.delete_btn = delete_btn
        self.delete_effective = delete_effective
        self.deleted: list = []
        self.clicks: list = []
        self.mouse = _DeleteMouse(self)

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is trip_js.DETAIL_ROWS_JS:
            return {"n": len(self.rows), "rows": [{"i": i, "PARTNER": p} for i, p in enumerate(self.rows)]}
        if jsstr is trip_js.DETAIL_ROW_CLICK_JS:
            return {"x": 2, "y": 2}
        if jsstr is js_lib.GRID_CURRENT_ROW_JS:
            if not self.current_ok:
                return {"ok": False, "reason": "grid 미접근"}
            return {
                "ok": True, "current": self.current, "itemIndex": self.current,
                "dataRow": self.current, "rows": len(self.rows),
            }
        if jsstr is trip_js.BTN_BOX_JS:
            return {"x": 9, "y": 9} if self.delete_btn else None
        if jsstr is js_lib.MODALS_SNAPSHOT_JS:
            return []
        return None


async def test_delete_blank_row_deletes_only_blank_row():
    page = _DeletePage(rows=["한국도로공사", ""], current=1)
    r = await steps.delete_blank_row(page)
    assert r["ok"] is True and r["verified"] is True
    assert page.deleted == [1] and page.rows == ["한국도로공사"]


async def test_delete_blank_row_no_blank_is_noop():
    page = _DeletePage(rows=["한국도로공사"], current=0)
    r = await steps.delete_blank_row(page)
    assert r["ok"] is True and r["note"] == "빈 행 없음" and page.deleted == []


async def test_delete_blank_row_skips_when_current_is_data_row():
    """좌표 클릭이 빗나가 현재 행이 **데이터 행**이면 삭제하지 않는다(되돌릴 수 없는 액션)."""
    page = _DeletePage(rows=["한국도로공사", ""], current=0)  # 의도 bi=1 인데 current=0
    r = await steps.delete_blank_row(page)
    assert r["ok"] is True and r["verified"] is False and "삭제 건너뜀" in r["warn"]
    assert page.deleted == [] and page.rows == ["한국도로공사", ""]


async def test_delete_blank_row_skips_when_current_unreadable():
    """확인 불가여도 **진행하지 않는다** — 표준 실패정책의 의도된 예외(파괴적 액션 게이트)."""
    page = _DeletePage(rows=["한국도로공사", ""], current=1, current_ok=False)
    r = await steps.delete_blank_row(page)
    assert r["ok"] is True and r["verified"] is False and "삭제 건너뜀" in r["warn"]
    assert page.deleted == []


async def test_delete_blank_row_reports_failure_when_row_count_unchanged():
    page = _DeletePage(rows=["한국도로공사", ""], current=1, delete_effective=False)
    r = await steps.delete_blank_row(page)
    assert r["ok"] is False and "빈 행 삭제 실패" in r["reason"]


async def test_delete_blank_row_missing_delete_button_fails():
    page = _DeletePage(rows=["한국도로공사", ""], current=1, delete_btn=False)
    r = await steps.delete_blank_row(page)
    assert r["ok"] is False and "삭제 버튼" in r["reason"]


# ── register_counter_partner: 대리 신호(빈 행 +1) 대신 실제 값 확인 ─────────────
class _CounterMouse:
    def __init__(self, page) -> None:  # noqa: ANN001
        self._p = page

    async def click(self, x, y):  # noqa: ANN001
        self._p.popups = 1  # 🔍 클릭 → 거래처 팝업 오픈(개수 증가)

    async def dblclick(self, x, y):  # noqa: ANN001
        self._p.popups = 0  # 등록되며 팝업이 닫히고
        if self._p.registers:
            self._p.counter_vals = [self._p.self_name]  # 부가선택 행에 값이 붙는다
        self._p.rows.append("")  # 부작용: detail 빈 행 +1(ERP 동작)


class _CounterPage:
    """register_counter_partner 용 가짜 page — 부가선택 값과 팝업 개수를 실제로 들고 있다."""

    def __init__(self, *, self_name: str, registers: bool = True, found: bool = True) -> None:
        self.self_name = self_name
        self.registers = registers
        self.found = found
        self.counter_vals: list = []
        self.rows = ["한국도로공사"]
        self.popups = 0
        self.mouse = _CounterMouse(self)
        self.keyboard = _FakeKeyboard()

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is trip_js.COUNTER_SCROLL_JS:
            return self.found
        if jsstr is trip_js.COUNTER_PICKER_BOX_JS:
            return {"x": 5, "y": 5}
        if jsstr is trip_js.COUNTER_VALS_JS:
            return {"found": True, "vals": list(self.counter_vals)} if self.found else {"found": False}
        if jsstr is trip_js.DETAIL_ROWS_JS:
            return {"n": len(self.rows), "rows": [{"i": i, "PARTNER": p} for i, p in enumerate(self.rows)]}
        if jsstr is trip_js.PICKER_ROW_RECT_JS:
            return {"x": 7, "y": 7}
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self.popups
        if jsstr is js_lib.PICKER_ROWCOUNT_JS:
            return 120 if self.popups else -1
        if jsstr is js_lib.PICKER_SEARCH_JS:
            return {"ok": True, "field": "customTextBox"}
        if jsstr is js_lib.PICKER_READ_MULTI_JS:
            return {"rows": 1, "options": [{"i": 0, "PARTNER_CD": "2026032511", "PARTNER_NM": self.self_name}]}
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.popups = 0
            return True
        return None


async def test_register_counter_partner_verifies_actual_value():
    page = _CounterPage(self_name="이트라이브2")
    r = await steps.register_counter_partner(page, "이트라이브2")
    assert r["ok"] is True and r["verified"] is True and r["blank_added"] is True


async def test_register_counter_partner_blank_row_alone_is_not_success():
    """빈 행은 늘었는데 값이 안 붙은 경우 — 예전 대리 신호로는 통과하던 자리다(하드 실패)."""
    page = _CounterPage(self_name="이트라이브2", registers=False)
    r = await steps.register_counter_partner(page, "이트라이브2")
    assert r["ok"] is False and "상대계정 등록 미반영" in r["reason"]


async def test_register_counter_partner_missing_item_skips():
    # 문서유형에 상대계정거래처 항목이 없음 → 우아한 스킵(오등록·오류 대신).
    page = _CounterPage(self_name="이트라이브2", found=False)
    r = await steps.register_counter_partner(page, "이트라이브2")
    assert r["ok"] is True and r["skipped"] is True


# ── type_amount: 잔존 확인 모달 / 에디터 준비 재시도 ──────────────────────────
class _Locator:
    async def click(self):
        return None

    async def select_text(self):
        return None

    async def press_sequentially(self, text, delay=None):  # noqa: ANN001
        return None

    async def press(self, key):  # noqa: ANN001
        return None


class _AmountMouse:
    """'확인' 버튼(3,3) 실클릭이 있어야 예산현황 모달이 실제로 닫힌다."""

    def __init__(self, page) -> None:  # noqa: ANN001
        self._p = page

    async def click(self, x, y):  # noqa: ANN001
        if (x, y) == (3, 3) and self._p.modal_left > 0:
            self._p.modal_left -= 1


class _AmountTypePage:
    """type_amount 용 가짜 page — 에디터 준비 회차와 예산현황 모달 잔존을 모사한다.

    실물 시맨틱: 모달은 '확인' 버튼을 **실제로 클릭했을 때만** 닫히고, 버튼을 못 찾으면
    (modal_closable=False) 영영 남는다 — 잔존 k-window 는 이후 피커 오독·F7 삼킴의 원인.
    """

    def __init__(self, *, amount: int, editor_ready_at: int = 1, modal_rounds: int = 1,
                 modal_closable: bool = True) -> None:
        self._amount = amount
        self._editor_ready_at = editor_ready_at
        self._editor_reads = 0
        self.modal_left = modal_rounds
        self._modal_closable = modal_closable
        self.editor_opens = 0
        self.mouse = _AmountMouse(self)

    def locator(self, sel):  # noqa: ANN001
        return _Locator()

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.OPEN_DETAIL_CELL_EDITOR_JS:
            self.editor_opens += 1
            return {"ok": True}
        if jsstr is trip_js.AMOUNT_EDITOR_INPUT_JS:
            self._editor_reads += 1
            return {"x": 1, "y": 1, "id": "gridDetail_number_1"} if self._editor_reads >= self._editor_ready_at else None
        if jsstr is js_lib.MODALS_SNAPSHOT_JS:
            return [{"title": "예산현황", "text": "", "buttons": ["확인"]}] * (1 if self.modal_left > 0 else 0)
        if jsstr is js_lib.MODAL_BTN_BOX_JS:
            if not self._modal_closable:
                return None
            return {"x": 3, "y": 3, "title": "예산현황"}
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self.modal_left
        if jsstr is trip_js.READ_AMT_JS:
            return {"SPPRC_AMT2": f"{self._amount:,}", "SPPRC_AMT": "0", "TOTAL_AMT": "0"}
        return None


async def test_type_amount_success_after_budget_modal():
    page = _AmountTypePage(amount=15400)
    r = await steps.type_amount(page, 15400)
    assert r["ok"] is True and r["modals"] == ["예산현황"]


async def test_type_amount_retries_editor_open_before_failing():
    # 고정 500ms 1회 읽기였다면 실패했을 느린 세션 — 커널 재시도(+에디터 재오픈)로 살린다.
    page = _AmountTypePage(amount=15400, editor_ready_at=3)
    r = await steps.type_amount(page, 15400)
    assert r["ok"] is True and page.editor_opens >= 2


async def test_type_amount_leftover_modal_fails_hard():
    # 버튼을 못 찾아 모달이 남은 채 진행하면 이후 피커 오독·F7 삼킴 → 여기서 끊는다.
    page = _AmountTypePage(amount=15400, modal_closable=False)
    r = await steps.type_amount(page, 15400)
    assert r["ok"] is False and "닫히지 않았습니다" in r["reason"]


async def test_type_amount_mismatch_fails_hard():
    page = _AmountTypePage(amount=999)
    r = await steps.type_amount(page, 15400)
    assert r["ok"] is False and "금액 반영 불일치" in r["reason"]


# ── _open_detail_cell_picker: 스테일 팝업을 '열렸다'로 오독하지 않는다 ──────────
class _OpenMouse:
    def __init__(self, page) -> None:  # noqa: ANN001
        self._p = page

    async def click(self, x, y):  # noqa: ANN001
        self._p.mag_clicks += 1
        if self._p.opens_at is not None and self._p.mag_clicks >= self._p.opens_at:
            self._p.popups += 1


class _OpenPickerPage:
    """돋보기 클릭 → 팝업 오픈을 모사. stale_popups 는 **직전 피커가 안 닫힌** 상태를 뜻한다.

    실물 시맨틱의 핵심: `PICKER_ROWCOUNT_JS` 는 '최상단 비-법인카드 k-window' 의 행수라
    잔존 팝업이 있으면 새 팝업이 안 떠도 ready(>=0) 를 낸다 → 개수 변화로만 오픈을 판정해야 한다.
    """

    def __init__(self, *, opens_at: int | None = 1, stale_popups: int = 0, rowcount: int = 33) -> None:
        self.opens_at = opens_at
        self.popups = stale_popups
        self._rowcount = rowcount
        self.mag_clicks = 0
        self.closes = 0
        self.mouse = _OpenMouse(self)

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.OPEN_DETAIL_CELL_EDITOR_JS:
            return {"ok": True}
        if jsstr is js_lib.DETAIL_EDITOR_MAGNIFIER_JS:
            return {"x": 1, "y": 1}
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self.popups
        if jsstr is js_lib.PICKER_ROWCOUNT_JS:
            # 잔존이든 새 팝업이든 '최상단'이 있으면 ready 를 낸다(오독의 원천).
            return self._rowcount if self.popups else -1
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.closes += 1
            self.popups = 0
            return True
        return None


async def test_open_detail_cell_picker_success():
    page = _OpenPickerPage()
    r = await steps._open_detail_cell_picker(page, "BG_NM", "예산단위")
    assert r["ok"] is True and page.popups == 1


async def test_open_detail_cell_picker_rejects_stale_popup():
    """직전 피커가 남아 있고 새 팝업은 안 뜨는 상황 — rowcount 만 보면 '열렸다'로 통과하던 자리."""
    page = _OpenPickerPage(opens_at=None, stale_popups=1)
    r = await steps._open_detail_cell_picker(page, "BG_NM", "예산단위")
    assert r["ok"] is False and "열리지 않았습니다" in r["reason"]
    assert page.closes >= 1  # 재시도 전에 잔존 팝업을 닫았다.


# ── fill_budget_fixed: 검색 정착 전 읽기(필터 전 전량) → 재검색으로 확정 ────────
class _BudgetMouse:
    def __init__(self, page) -> None:  # noqa: ANN001
        self._p = page

    async def click(self, x, y):  # noqa: ANN001
        if (x, y) == (1, 1):  # 돋보기
            self._p.popups += 1
        elif (x, y) == (4, 4):  # '적용'
            self._p.cell = self._p.selected
            self._p.popups = 0


_BG_FILTERED = [
    {"i": 0, "BG_CD": "2010", "BG_NM": "인사기획팀", "BIZPLAN_NM": "운영비", "BGACCT_NM": "(판)여비교통비-국내출장"},
]
# 검색 필터가 걸리기 전 전량 — 같은 부서가 서로 다른 BG_CD 로 섞여 있어 '다중매칭' 이 된다.
_BG_UNFILTERED = _BG_FILTERED + [
    {"i": 1, "BG_CD": "9999", "BG_NM": "인사기획팀", "BIZPLAN_NM": "별도", "BGACCT_NM": "(판)여비교통비-국내출장"},
]


class _BudgetPage:
    """fill_budget_fixed 전 구간(오픈→검색→선택→적용) 가짜 page.

    settle_at=2 : **첫 읽기는 필터 전 전량**(다중매칭), 두 번째 읽기에서 33행으로 좁혀진다 —
    재검색 안전판이 없으면 그대로 실패하던 자리(예산단위/프로젝트에는 재시도가 아예 없었다).
    """

    def __init__(self, *, settle_at: int = 1) -> None:
        self._settle_at = settle_at
        self.reads = 0
        self.popups = 0
        self.cell = ""
        self.selected = "인사기획팀"
        self.mouse = _BudgetMouse(self)
        self.keyboard = _FakeKeyboard()

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.OPEN_DETAIL_CELL_EDITOR_JS:
            return {"ok": True}
        if jsstr is js_lib.DETAIL_EDITOR_MAGNIFIER_JS:
            return {"x": 1, "y": 1}
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self.popups
        if jsstr is js_lib.PICKER_ROWCOUNT_JS:
            return (len(_BG_FILTERED) if self.reads >= self._settle_at else len(_BG_UNFILTERED)) if self.popups else -1
        if jsstr is js_lib.PICKER_SEARCH_JS:
            return {"ok": True, "field": "customTextBox"}
        if jsstr is js_lib.PICKER_READ_MULTI_JS:
            self.reads += 1
            return {"options": _BG_FILTERED if self.reads >= self._settle_at else _BG_UNFILTERED}
        if jsstr is js_lib.PICKER_SELECT_JS:
            return {"ok": True}
        if jsstr is js_lib.PICKER_APPLY_BTN_JS:
            return {"x": 4, "y": 4}
        if jsstr is js_lib.GRID_CELL_VALUE_JS:
            f = arg["field"]
            return {"ok": True, "row": 0, "rows": 1, "raw": {f: self.cell}, "compact": {f: ""}, "display": {f: None}}
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.popups = 0
            return True
        return None


async def test_fill_budget_fixed_settled_first_read():
    page = _BudgetPage()
    r = await steps.fill_budget_fixed(page, "인사기획팀", "판관비")
    assert r["ok"] is True and r["code"] == "2010" and page.reads == 1


async def test_fill_budget_fixed_retries_search_when_read_was_prefilter():
    """정착 전 읽기(전량 → 다중매칭)를 재검색으로 살린다 — 예전엔 재시도 0회라 그대로 실패했다."""
    page = _BudgetPage(settle_at=2)
    r = await steps.fill_budget_fixed(page, "인사기획팀", "판관비")
    assert r["ok"] is True and r["code"] == "2010" and page.reads >= 2


async def test_fill_budget_fixed_gives_up_and_closes_popup():
    page = _BudgetPage(settle_at=99)  # 끝내 필터가 안 걸림 → 다중매칭으로 실패 + 팝업 닫힘.
    r = await steps.fill_budget_fixed(page, "인사기획팀", "판관비")
    assert r["ok"] is False and "다중매칭" in r["reason"] and page.popups == 0
