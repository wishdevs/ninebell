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


class _FakeMouse:
    async def click(self, x, y):  # noqa: ANN001
        return None


class _FakePartnerPage:
    """dump_partners 의 evaluate 호출을 JS 식별로 디스패치하는 최소 가짜 page.

    rowcount 를 상수로 고정해 '증가 없음 → 3회 stable → 종료' 경로를 태운다.
    """

    def __init__(self, rowcount: int, options: list[dict]) -> None:
        self._rowcount = rowcount
        self._options = options
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse()
        self.closed = False
        self.read_calls = 0

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.PICKER_ROWCOUNT_JS:
            return self._rowcount
        if jsstr is js_lib.PICKER_SEARCH_JS:
            return {"ok": True, "field": "customTextBox"}
        if jsstr is js_lib.PICKER_FOCUS_LAST_JS:
            return {"ok": True, "row": self._rowcount - 1}
        if jsstr is js_lib.PICKER_READ_MULTI_JS:
            self.read_calls += 1
            return {"rows": self._rowcount, "options": self._options}
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.closed = True
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


class _ApplyPage:
    """_select_and_apply 의 evaluate 를 JS 식별로 디스패치하는 최소 가짜 page."""

    def __init__(self, *, apply_box, cell_value: str, gone: bool = True) -> None:
        self._apply_box = apply_box
        self._cell = cell_value
        self._gone = gone
        self.mouse = _FakeMouse()
        self.closed = False

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.PICKER_SELECT_JS:
            return {"ok": True}
        if jsstr is js_lib.PICKER_APPLY_BTN_JS:
            return self._apply_box
        if jsstr is trip_js.READ_DETAIL_CELL_JS:
            return {"ok": True, "values": {arg[0]: self._cell}}
        if jsstr is js_lib.PICKER_ROWCOUNT_JS:
            return -1 if self._gone else 5
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.closed = True
            return True
        return None


async def test_select_and_apply_success():
    page = _ApplyPage(apply_box={"x": 1, "y": 1}, cell_value="한국도로공사")
    r = await steps._select_and_apply(page, 0, "거래처", "PARTNER_NM", "한국도로공사")
    assert r["ok"] is True and page.closed is False


async def test_select_and_apply_missing_apply_button_fails():
    page = _ApplyPage(apply_box=None, cell_value="한국도로공사")
    r = await steps._select_and_apply(page, 0, "거래처", "PARTNER_NM", "한국도로공사")
    assert r["ok"] is False and "적용" in r["reason"] and page.closed is True


async def test_select_and_apply_cell_not_reflected_fails():
    page = _ApplyPage(apply_box={"x": 1, "y": 1}, cell_value="")  # 셀 미반영
    r = await steps._select_and_apply(page, 0, "예산단위", "BG_NM", "인사기획팀")
    assert r["ok"] is False and "미반영" in r["reason"] and page.closed is True


async def test_select_and_apply_popup_not_closed_fails():
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
