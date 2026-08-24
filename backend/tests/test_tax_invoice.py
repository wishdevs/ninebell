"""세금계산서(tax-invoice) — evidence_for·params 정규화·분할 금액·노드 계약·픽스처 lockstep.

브라우저 스텝(피커·타이핑)은 국내출장 재사용이라 trip 테스트가 커버하고, 여기선 세금계산서
고유분(증빙 도출 10코드+불변식·FE evidenceFor 패리티·분할 금액 계산·다이얼로그 응답 분기·
노드 조립 순서·State 계약·워크플로우 등록·픽스처 steps↔그래프 노드 lockstep)을 강제한다.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.agents.tax_invoice import js as ti_js
from app.agents.tax_invoice import steps
from app.agents.tax_invoice.graph import (
    TAX_INVOICE_FG_CODE,
    TAX_INVOICE_GUBUN_LABEL,
    TaxInvoiceState,
    build_tax_invoice_graph,
)
from app.agents.tax_invoice.nodes import apply as apply_mod
from app.agents.tax_invoice.nodes import evdn as evdn_mod
from app.agents.tax_invoice.nodes import fill as fill_mod
from app.agents.tax_invoice.nodes import invoice_pick as pick_mod
from app.agents.tax_invoice.nodes import split as split_mod
from app.agents.tax_invoice.nodes.save import make_save_doc_node
from app.agents.tax_invoice.nodes.validate import make_validate_params_node
from app.agents.tax_invoice.params import (
    EVIDENCE_LABEL,
    evidence_for,
    parse_tax_invoice_params,
    resolve_split_amounts,
)
from nbkit.omnisol import js_lib
from tests.support.state_contract import assert_keys_declared

# ── FE 미러(model.ts) — 패리티 소스(pre-run 폼 승격으로 simulation→pre-run 이동) ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODEL_TS = _REPO_ROOT / "src" / "components" / "live" / "pre-run" / "tax-invoice" / "model.ts"

# FE 값 → BE params 계약 값 번역표.
_FE_ISSUE = {"before": "pre", "after": "post"}
_FE_SPLIT = {"single": False, "split": True}
_FE_ND = {"no-business": "none_biz", "small-car": "car", "exempt-business": "exempt_biz"}


def _ti(**over) -> dict:
    """발행 전(22) 유효 최소 입력 — 케이스별 오버라이드."""
    base = {
        "issue": "pre",
        "tax": "taxable",
        "nondeduct_reason": None,
        "split": False,
        "partner_name": "코웨이(주)",
        "supply_amount": 37_000,
        "budget_unit_name": "임원실",
        "project_wbs": "800",
        "note": "옴니솔테스트",
    }
    base.update(over)
    return {"tax_invoice": base}


def _split_rows(*rows) -> list[dict]:
    out = []
    for note, amount, cc, wbs in rows:
        out.append({"note": note, "amount": amount, "cost_center": cc, "project_wbs": wbs})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# evidence_for — 10코드 전 조합 + 불변식
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    ("issue", "split", "tax", "nd", "code"),
    [
        ("post", False, "taxable", None, "03"),
        ("post", False, "exempt", None, "04"),
        ("post", False, "nondeduct", "none_biz", "05"),
        ("post", False, "nondeduct", "car", "06"),
        ("post", False, "nondeduct", "exempt_biz", "07"),
        ("post", True, "taxable", None, "11"),
        ("post", True, "exempt", None, "13"),
        ("pre", False, "taxable", None, "22"),
        ("pre", False, "exempt", None, "23"),
        ("pre", False, "nondeduct", None, "24"),
    ],
)
def test_evidence_for_all_codes(issue, split, tax, nd, code):
    assert evidence_for(issue, split, tax, nd) == code


def test_evidence_pre_nondeduct_ignores_reason():
    # 발행 전 불공은 사유 무구분 — 사유가 와도 24 하나(FE evidenceFor 동일).
    assert evidence_for("pre", False, "nondeduct", "car") == "24"


def test_evidence_invariant_nondeduct_split():
    with pytest.raises(ValueError, match="불공"):
        evidence_for("post", True, "nondeduct", "car")


def test_evidence_invariant_pre_split():
    with pytest.raises(ValueError, match="발행 전"):
        evidence_for("pre", True, "taxable", None)


def test_evidence_post_nondeduct_requires_reason():
    with pytest.raises(ValueError, match="사유"):
        evidence_for("post", False, "nondeduct", None)


def test_evidence_bad_issue_and_tax():
    with pytest.raises(ValueError, match="issue"):
        evidence_for("both", False, "taxable", None)
    with pytest.raises(ValueError, match="tax"):
        evidence_for("pre", False, "vat", None)


# ── FE evidenceFor 패리티(model.ts QUICK_PICK_GROUPS 리터럴 — 10코드 전 조합) ──
def test_fe_quick_pick_mapping_parity():
    """FE 바로선택 표(코드↔답 조합 1:1)가 서버 evidence_for 와 동일해야 한다(드리프트 감시)."""
    src = _MODEL_TS.read_text(encoding="utf-8")
    block = src.split("QUICK_PICK_GROUPS", 1)[1]
    picks = re.findall(
        r"code:\s*'(\d+)'[\s\S]*?issue:\s*'(\w+)'[\s\S]*?split:\s*'(\w+)'"
        r"[\s\S]*?tax:\s*'(\w+)'[\s\S]*?nondeduct:\s*(null|'[a-z-]+')",
        block,
    )
    assert len(picks) == 10, f"model.ts QUICK_PICK_GROUPS 추출 실패(형태 변경 시 정규식 갱신): {len(picks)}건"
    for code, fe_issue, fe_split, fe_tax, fe_nd in picks:
        nd = None if fe_nd == "null" else _FE_ND[fe_nd.strip("'")]
        got = evidence_for(_FE_ISSUE[fe_issue], _FE_SPLIT[fe_split], fe_tax, nd)
        assert got == code, (
            f"FE/BE 증빙 매핑 드리프트 — 조합({fe_issue},{fe_split},{fe_tax},{fe_nd}) "
            f"FE={code} BE={got}"
        )


def test_fe_evidence_label_parity():
    src = _MODEL_TS.read_text(encoding="utf-8")
    m = re.search(r"EVIDENCE_LABEL: Record<string, string> = \{(.*?)\};", src, re.DOTALL)
    assert m, "model.ts 에서 EVIDENCE_LABEL 리터럴을 찾지 못했습니다"
    fe = dict(re.findall(r"'(\d+)':\s*'([^']+)'", m.group(1)))
    assert fe == EVIDENCE_LABEL, f"증빙 라벨 FE/BE 드리프트 — FE={fe} BE={EVIDENCE_LABEL}"


# ══════════════════════════════════════════════════════════════════════════════
# parse_tax_invoice_params — 정규화·한국어 오류
# ══════════════════════════════════════════════════════════════════════════════
def test_parse_pre_minimal_ok():
    plan = parse_tax_invoice_params(_ti())
    assert plan["evidence_code"] == "22"
    assert plan["partner_name"] == "코웨이(주)"
    assert plan["supply_amount"] == 37_000
    assert plan["period_from"] is None and plan["period_to"] is None  # 발행 전은 조회기간 없음.
    assert plan["actg_date_compact"] is None
    assert plan["exempt_reason"] is None
    assert plan["split_rows"] == []


def test_parse_pre_negative_supply_allowed():
    plan = parse_tax_invoice_params(_ti(supply_amount=-214_000))
    assert plan["supply_amount"] == -214_000


def test_parse_pre_actg_date_compact():
    plan = parse_tax_invoice_params(_ti(actg_date="2026-08-14"))
    assert plan["actg_date_compact"] == "20260814"


def test_parse_post_defaults_period_this_month():
    from datetime import date

    plan = parse_tax_invoice_params(
        _ti(issue="post", partner_name=None, supply_amount=None)
    )
    assert plan["evidence_code"] == "03"
    today = date.today()
    assert plan["period_from"] == today.replace(day=1).isoformat()
    assert plan["period_to"] == today.isoformat()
    assert plan["actg_date_compact"] is None  # 발행 후 회계일은 선택 행 계산서일 자동(D9).


def test_parse_post_actg_date_ignored():
    plan = parse_tax_invoice_params(
        _ti(issue="post", partner_name=None, supply_amount=None, actg_date="2026-08-01")
    )
    assert plan["actg_date_compact"] is None


def test_parse_exempt_reason_defaults():
    plan = parse_tax_invoice_params(_ti(tax="exempt"))
    assert plan["evidence_code"] == "23"
    assert plan["exempt_reason"] == "일반면세"


def test_parse_missing_tax_invoice():
    with pytest.raises(ValueError, match="tax_invoice"):
        parse_tax_invoice_params({})


def test_parse_pre_requires_partner():
    with pytest.raises(ValueError, match="거래처"):
        parse_tax_invoice_params(_ti(partner_name=None))


def test_parse_pre_requires_supply():
    with pytest.raises(ValueError, match="공급가액"):
        parse_tax_invoice_params(_ti(supply_amount=None))


def test_parse_zero_supply_rejected():
    with pytest.raises(ValueError, match="0원"):
        parse_tax_invoice_params(_ti(supply_amount=0))


def test_parse_supply_must_be_int():
    with pytest.raises(ValueError, match="정수"):
        parse_tax_invoice_params(_ti(supply_amount="37000"))


def test_parse_note_required_and_max_len():
    with pytest.raises(ValueError, match="적요"):
        parse_tax_invoice_params(_ti(note=""))
    with pytest.raises(ValueError, match="200"):
        parse_tax_invoice_params(_ti(note="가" * 201))


def test_parse_budget_and_project_required():
    with pytest.raises(ValueError, match="예산단위"):
        parse_tax_invoice_params(_ti(budget_unit_name=""))
    with pytest.raises(ValueError, match="프로젝트"):
        parse_tax_invoice_params(_ti(project_wbs=""))


def test_parse_bad_nondeduct_reason_value():
    with pytest.raises(ValueError, match="nondeduct_reason"):
        parse_tax_invoice_params(_ti(tax="nondeduct", nondeduct_reason="whatever"))


def test_parse_period_reversed():
    with pytest.raises(ValueError, match="조회기간"):
        parse_tax_invoice_params(
            _ti(issue="post", partner_name=None, supply_amount=None,
                period_from="2026-08-10", period_to="2026-08-01")
        )


def test_parse_bad_period_format():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_tax_invoice_params(
            _ti(issue="post", partner_name=None, supply_amount=None, period_from="08/01/2026")
        )


# ── 분할(split) 정규화 ───────────────────────────────────────────────────────
def _split_ti(**over) -> dict:
    base = _ti(
        issue="post",
        split=True,
        supply_amount=84_000,
        split_rows=_split_rows(("분할행1", 42_000, "경영지원팀", "800"), ("분할행2", None, "개발팀", "800")),
    )
    base["tax_invoice"].update(over)
    return base


def test_parse_split_balance_last():
    plan = parse_tax_invoice_params(_split_ti())
    assert plan["evidence_code"] == "11"
    assert plan["split_manual"] is True  # 거래처+공급가액 제공 = 수동분할(프로브 검증 레시피).
    assert plan["split_balance_last"] is True
    assert [r["amount"] for r in plan["split_rows"]] == [42_000, 42_000]  # 잔액 = 차액.
    assert plan["split_rows"][1]["cost_center"] == "개발팀"


def test_parse_split_auto_mode_without_partner_supply():
    # 자동분할(FE 발행 후 폼): 거래처·공급가액 없이 계산서 행 선택(HITL)이 채운다 —
    # 총액 미정이라 마지막 행 차액반영(amount=None)이 필수이고 잔액은 계산하지 않는다.
    plan = parse_tax_invoice_params(_split_ti(partner_name=None, supply_amount=None))
    assert plan["split_manual"] is False
    assert plan["split_balance_last"] is True
    assert [r["amount"] for r in plan["split_rows"]] == [42_000, None]
    with pytest.raises(ValueError, match="차액반영"):
        parse_tax_invoice_params(
            _split_ti(
                partner_name=None,
                supply_amount=None,
                split_rows=_split_rows(("a", 42_000, "팀A", "800"), ("b", 42_000, "팀B", "800")),
            )
        )


def test_parse_split_all_explicit_sum_must_match():
    plan = parse_tax_invoice_params(
        _split_ti(split_rows=_split_rows(("a", 50_000, "팀A", "800"), ("b", 34_000, "팀B", "800")))
    )
    assert plan["split_balance_last"] is False
    with pytest.raises(ValueError, match="합계"):
        parse_tax_invoice_params(
            _split_ti(split_rows=_split_rows(("a", 50_000, "팀A", "800"), ("b", 30_000, "팀B", "800")))
        )


def test_parse_split_partner_supply_must_come_together():
    # 수동분할은 거래처·공급가액이 쌍 — 한쪽만 있으면 모드가 특정 안 돼 한국어 오류.
    with pytest.raises(ValueError, match="함께"):
        parse_tax_invoice_params(_split_ti(partner_name=None))
    with pytest.raises(ValueError, match="함께"):
        parse_tax_invoice_params(_split_ti(supply_amount=None))


def test_parse_split_negative_total_rejected():
    # 불변식 '분할 합계>0' — 취소분 상계로 총액이 0/음수면 분할 불가(PROCESS.md 노티스).
    with pytest.raises(ValueError, match="0보다"):
        parse_tax_invoice_params(_split_ti(supply_amount=-84_000))


def test_parse_split_invariants_via_params():
    with pytest.raises(ValueError, match="불공"):
        parse_tax_invoice_params(_split_ti(tax="nondeduct", nondeduct_reason="car"))
    with pytest.raises(ValueError, match="발행 전"):
        parse_tax_invoice_params(_split_ti(issue="pre"))


def test_parse_post_body_fields_come_from_hitl():
    """발행 후 폼은 질문+조회기간만 — 적요·예산단위·프로젝트는 개입에서 받는다(D1 2026-08-20)."""
    plan = parse_tax_invoice_params(
        _ti(issue="post", partner_name=None, supply_amount=None,
            budget_unit_name=None, project_wbs=None, note=None)
    )
    assert plan["evidence_code"] == "03"
    assert plan["note"] == "" and plan["budget_unit_name"] == "" and plan["project_wbs"] == ""


def test_parse_split_plan_optional_from_hitl():
    # 분할 계획도 개입(splitPlan)에서 받는다 — 폼이 비워 보내도 통과한다.
    plan = parse_tax_invoice_params(_split_ti(split_rows=None))
    assert plan["split"] is True and plan["split_rows"] == []


def test_parse_split_rows_required_fields():
    with pytest.raises(ValueError, match="비용센터"):
        parse_tax_invoice_params(
            _split_ti(split_rows=_split_rows(("a", 42_000, "", "800"), ("b", None, "팀B", "800")))
        )
    with pytest.raises(ValueError, match="적요"):
        parse_tax_invoice_params(
            _split_ti(split_rows=_split_rows(("", 42_000, "팀A", "800"), ("b", None, "팀B", "800")))
        )
    with pytest.raises(ValueError, match="프로젝트"):
        parse_tax_invoice_params(
            _split_ti(split_rows=_split_rows(("a", 42_000, "팀A", ""), ("b", None, "팀B", "800")))
        )


# ── resolve_split_amounts — 잔돈·음수·합계 검증(Decimal, round() 금지) ────────
def test_resolve_remainder_absorbs_odd_change():
    fixed, via_balance = resolve_split_amounts(100_003, [33_334, 33_334, None])
    assert via_balance is True
    assert fixed == [33_334, 33_334, 33_335]
    assert sum(fixed) == 100_003


def test_resolve_negative_explicit_row_allowed():
    fixed, _ = resolve_split_amounts(84_000, [100_000, -50_000, None])
    assert fixed == [100_000, -50_000, 34_000]


def test_resolve_null_only_last():
    with pytest.raises(ValueError, match="마지막 행"):
        resolve_split_amounts(84_000, [None, 42_000])


def test_resolve_zero_remainder_rejected():
    with pytest.raises(ValueError, match="차액이 0원"):
        resolve_split_amounts(84_000, [84_000, None])


def test_resolve_zero_explicit_rejected():
    with pytest.raises(ValueError, match="0원"):
        resolve_split_amounts(84_000, [0, None])


def test_resolve_row_count_bounds():
    with pytest.raises(ValueError, match="2~20행"):
        resolve_split_amounts(84_000, [None])
    with pytest.raises(ValueError, match="2~20행"):
        resolve_split_amounts(84_000, [1_000] * 20 + [None])


def test_resolve_bool_amount_rejected():
    with pytest.raises(ValueError, match="정수"):
        resolve_split_amounts(84_000, [True, None])


def test_resolve_without_supply_keeps_last_none():
    fixed, via_balance = resolve_split_amounts(None, [42_000, None])
    assert via_balance is True
    assert fixed == [42_000, None]  # 잔액 미계산 — ERP 차액반영이 흡수.
    with pytest.raises(ValueError, match="차액반영"):
        resolve_split_amounts(None, [42_000, 42_000])


# ══════════════════════════════════════════════════════════════════════════════
# steps 순수 헬퍼
# ══════════════════════════════════════════════════════════════════════════════
def test_evdn_dialog_answer_matrix():
    # 발행 전만 "아니요" — 발행 후는 분할(수동/자동) 여부와 무관하게 "예"(프로브 Case B 실측).
    assert steps.evdn_dialog_answer("pre") == "아니요"
    assert steps.evdn_dialog_answer("post") == "예"


def test_pick_row_by_text():
    rows = [{"A": "일반과세", "B": 1}, {"A": "일반면세", "B": 2}]
    idx, row = steps.pick_row_by_text(rows, "일반면세")
    assert idx == 1 and row["B"] == 2
    assert steps.pick_row_by_text(rows, "없는값") == (None, None)


def test_pick_budget_by_name_exact_and_ambiguous():
    opts = [
        {"BG_CD": "1000", "BG_NM": "임원실"},
        {"BG_CD": "1100", "BG_NM": "임원실2"},
    ]
    row, err = steps.pick_budget_by_name(opts, "임원실")
    assert err is None and row["BG_CD"] == "1000"
    _, err = steps.pick_budget_by_name(opts, "없는팀")
    assert err and "일치 없음" in err
    dup = [{"BG_CD": "1", "BG_NM": "총무"}, {"BG_CD": "2", "BG_NM": "총무"}]
    _, err = steps.pick_budget_by_name(dup, "총무")
    assert err and "여러 건" in err


def test_balance_and_orphan_row_helpers():
    rows = [
        {"NOTE_DC": "분할행1", "SPPRC_AMT2": 42_000},
        {"NOTE_DC": "분할행2", "SPPRC_AMT2": None},  # 미리 만든 빈 행(고아).
        {"NOTE_DC": None, "SPPRC_AMT2": 42_000},  # 차액반영이 만든 잔액행.
    ]
    assert steps.balance_row_index(rows) == 2
    assert steps.orphan_row_indexes(rows) == [1]


# ── open_invoice_list — 게이트 닫힘 검증 + 팝업 창 스코프 조회 실행 ────────────────
def _inv_rows(n: int) -> list[dict]:
    return [{"START_DT": "2026-08-03", "PARTNER_NM": f"거래처{i}", "SPPRC_AMT": 1_000 * (i + 1)} for i in range(n)]


def test_best_invoice_grid_picks_result_grid():
    # 팝업에 그리드가 여러 개면 결과 그리드(행수 최대)를 고른다 — 앞선 빈 조건 그리드 회피.
    state = {"grids": [{"gridIndex": 0, "n": 0, "rows": []}, {"gridIndex": 1, "n": 36, "rows": [{"a": 1}]}]}
    assert steps.best_invoice_grid(state)["gridIndex"] == 1
    # 읽기 실패(dewsControl 미바인딩) 그리드는 후보에서 제외.
    state_err = {"grids": [{"gridIndex": 0, "err": "TypeError"}, {"gridIndex": 1, "n": 0, "rows": []}]}
    assert steps.best_invoice_grid(state_err)["gridIndex"] == 1
    # 전부 0행이면 첫 정상 그리드(0행 판정 대상도 실제 그리드여야 한다).
    assert steps.best_invoice_grid({"grids": [{"gridIndex": 0, "n": 0}, {"gridIndex": 1, "n": 0}]})["gridIndex"] == 0
    # 전부 읽기 실패 / 그리드 없음 = None.
    assert steps.best_invoice_grid({"grids": [{"gridIndex": 0, "err": "x"}]}) is None
    assert steps.best_invoice_grid({}) is None


_GRID_TYPE_ERROR = "TypeError: Cannot read properties of undefined (reading '_grid')"


class _InvoicePopupPage:
    """조회(F2)→게이트('선택')→전자세금계산서 팝업 흐름 시뮬 — A/B 진단 실측 상태를 그대로 흉내.

    실측 계약: ① 게이트 다이얼로그가 **닫히기 전까지 팝업 그리드는 dewsControl 미바인딩**
    (읽기 시 TypeError) ② 팝업은 열려도 자동 조회하지 않는다(조회 전 0행) ③ 조회는 팝업 창
    DOM 안의 '조회' 버튼을 눌러야 돈다 — 좌표 클릭은 본창 조회를 때리므로 이 스텁은 좌표
    클릭에 **아무 반응도 하지 않는다**(회귀 가드).
    """

    def __init__(self, *, popup: bool = True, buttons: tuple[str, ...] = ("품목정보", "조회", "일괄적용", "적용", "닫기"),
                 rows: list[dict] | None = None, counts_after_query: list[int] | None = None,
                 other_titles: tuple[str, ...] = ("공지",),
                 grid_never_binds: bool = False, swallow_clicks: int = 0,
                 extra_empty_grid: bool = False) -> None:
        self._popup = popup
        self._buttons = list(buttons)
        self._rows = rows if rows is not None else _inv_rows(36)
        self._counts = list(counts_after_query) if counts_after_query else [len(self._rows)]
        self._other = list(other_titles)
        self._grid_never_binds = grid_never_binds
        self._swallow = swallow_clicks
        self._extra_empty_grid = extra_empty_grid
        self.queried = False
        self.query_clicks = 0

        self.clicks: list = []  # 좌표 클릭(있으면 회귀) — mouse.click 기록.
        self.click_payloads: list = []  # CLICK_WINDOW_BUTTON_JS 인자.
        self.state_args: list = []
        self.period: dict | None = None
        self.mouse = _InertMouse(self)



    def _next_count(self) -> int:
        if not self.queried:
            return 0  # 팝업 오픈 직후 — 자동 조회 없음(진단 실측).
        return self._counts.pop(0) if len(self._counts) > 1 else self._counts[0]

    def _grids(self, limit: int | None) -> list[dict]:
        if self._grid_never_binds:
            # 게이트 잔존 = 그리드 미초기화(A/B 진단의 TypeError 재현).
            return [{"gridIndex": 0, "elId": "taxGrid", "err": _GRID_TYPE_ERROR}]
        n = self._next_count()
        rows = [] if limit == 0 else self._rows[:n]
        result = {"gridIndex": 0, "elId": "taxGrid", "n": n, "rows": rows}
        if not self._extra_empty_grid:
            return [result]
        result["gridIndex"] = 1
        return [{"gridIndex": 0, "elId": "condGrid", "n": 0, "rows": []}, result]

    def _titles(self) -> list[str]:
        titles = []
        if self._popup:
            titles.append("전자세금계산서/전자계산서")
        titles.extend(self._other)
        return titles

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.MODALS_SNAPSHOT_JS:
            return []  # F2 를 안 누르므로 게이트 다이얼로그 자체가 없다.
        if js_src == ti_js.CLICK_WINDOW_BUTTON_JS:
            return self._click_window_button(arg or {})
        if js_src == ti_js.POPUP_BY_TITLE_STATE_JS:
            self.state_args.append(arg)
            if not self._popup:
                return {"ok": False, "reason": "no-popup", "titles": self._titles()}
            grids = self._grids((arg or {}).get("limit"))
            return {
                "ok": True, "title": "전자세금계산서/전자계산서", "topmost": False,
                "titles": self._titles(), "windowCount": len(self._titles()),
                "inputs": [{"id": "period_startinput", "value": ""}],
                "buttons": [{"text": t, "x": 1509, "y": 309} for t in self._buttons],
                "gridCount": len(grids), "grids": grids,
            }
        if js_src == ti_js.SET_INVOICE_PERIOD_JS:
            self.period = arg
            return {"start": True, "end": True}
        return True  # js_click(본창 조회 F2) 등 부수 평가.

    def _click_window_button(self, arg: dict) -> dict:
        """창 스코프 요소 클릭 — 게이트(textHint)와 팝업 조회(titleHints)를 구분해 처리."""
        self.click_payloads.append(arg)
        label = arg.get("label")
        # 팝업 조회 버튼(게이트 경로 없음 — F2 미클릭).
        if not self._popup:
            return {"ok": False, "reason": "no-window", "titles": self._titles()}
        if label not in self._buttons:
            return {"ok": False, "reason": "no-button", "titles": self._titles(), "buttons": list(self._buttons)}
        self.query_clicks += 1
        if self._swallow > 0:
            self._swallow -= 1  # 눌렸지만 조회가 돌지 않는 세션.
            return {"ok": True, "title": "전자세금계산서/전자계산서", "label": label}
        self.queried = True
        return {"ok": True, "title": "전자세금계산서/전자계산서", "label": label}

    async def wait_for_timeout(self, ms):
        return None


class _InertMouse:
    """좌표 클릭은 **아무 일도 하지 않는다** — 본창 조회를 때리는 경로의 회귀 가드."""

    def __init__(self, page: _InvoicePopupPage) -> None:
        self._page = page

    async def click(self, x, y):
        self._page.clicks.append((x, y))


async def test_open_invoice_list_starts_from_open_modal_without_f2():
    """모달은 증빙 적용이 이미 열어 뒀다 — 이 스텝은 F2 를 누르지 않고 모달 안에서만 조회한다."""
    page = _InvoicePopupPage()
    out = await steps.open_invoice_list(page, "2026-08-01", "2026-08-19")
    assert out["ok"] is True and len(out["rows"]) == 36
    assert page.clicks == []  # 좌표 클릭 0회(본창 조회·F2 오클릭 회귀 가드).
    payload = page.click_payloads[0]
    assert payload["titleHints"] == ["전자세금계산서", "전자계산서"] and payload["label"] == "조회"
    assert page.query_clicks == 1


async def test_open_invoice_list_fails_when_modal_absent():
    # 증빙 적용이 모달을 못 열었으면(세션 이상) 열린 창 목록을 실어 단락한다.
    page = _InvoicePopupPage(popup=False)
    out = await steps.open_invoice_list(page, "2026-08-01", "2026-08-19")
    assert out["ok"] is False
    assert "계산서 모달이 열리지 않았습니다" in out["reason"] and "공지" in out["reason"]


async def test_open_invoice_list_fails_when_grid_never_binds():
    # 게이트는 없는데 그리드가 끝내 미바인딩 — dewsControl 신호를 사유에 명시한다.
    page = _InvoicePopupPage(grid_never_binds=True)
    out = await steps.open_invoice_list(page, "2026-08-01", "2026-08-19")
    assert out["ok"] is False
    assert "초기화되지 않았습니다" in out["reason"] and "dewsControl" in out["reason"]
    assert page.query_clicks == 0


async def test_open_invoice_list_reports_popup_buttons_when_query_label_missing():
    # 팝업에 '조회'가 없으면 팝업 버튼 라벨을 사유에 실어 다음 실런이 스스로 말하게.
    page = _InvoicePopupPage(buttons=("품목정보", "일괄적용", "적용", "닫기"))
    out = await steps.open_invoice_list(page, "2026-08-01", "2026-08-19")
    assert out["ok"] is False
    assert "'조회' 버튼을 찾지 못했습니다" in out["reason"]
    assert "일괄적용" in out["reason"] and "품목정보" in out["reason"]


async def test_open_invoice_list_waits_out_slow_loading():
    # 로딩 지연: 조회 직후 0행 → 12행 → 36행. 중간값을 결과로 확정하면 안 된다.
    page = _InvoicePopupPage(counts_after_query=[0, 12, 36])
    out = await steps.open_invoice_list(page, "2026-08-01", "2026-08-19")
    assert out["ok"] is True and out["settled"] is True
    assert len(out["rows"]) == 36


async def test_open_invoice_list_retries_swallowed_query_click():
    # 첫 조회 클릭이 삼켜져도 0행으로 끝내지 않고 재조회로 회수한다.
    page = _InvoicePopupPage(swallow_clicks=1)
    out = await steps.open_invoice_list(page, "2026-08-01", "2026-08-19")
    assert out["ok"] is True and len(out["rows"]) == 36
    assert page.query_clicks == 2 and out["attempts"] == 2


async def test_open_invoice_list_reads_result_grid_not_empty_condition_grid():
    # 팝업에 빈 조건 그리드가 앞서 있어도 결과 그리드를 읽는다(첫 그리드 가정 금지).
    page = _InvoicePopupPage(extra_empty_grid=True)
    out = await steps.open_invoice_list(page, "2026-08-01", "2026-08-19")
    assert out["ok"] is True and len(out["rows"]) == 36


async def test_open_invoice_list_reports_real_zero_rows():
    # 진짜 0건 — 재조회까지 하고도 0행이면 그때 빈 결과로 확정한다.
    page = _InvoicePopupPage(rows=[], counts_after_query=[0])
    out = await steps.open_invoice_list(page, "2026-08-01", "2026-08-19")
    assert out["ok"] is True and out["rows"] == [] and out["settled"] is True
    assert page.query_clicks == 2 and out["attempts"] == 2


async def test_pick_invoices_node_reports_empty_period(monkeypatch):
    async def fake_open(page, f, t):
        return {"ok": True, "rows": [], "settled": True, "attempts": 2}

    monkeypatch.setattr(pick_mod.steps, "open_invoice_list", fake_open)
    node = pick_mod.make_pick_invoices_node()
    plan = parse_tax_invoice_params(_ti(issue="post", partner_name=None, supply_amount=None))
    out = await node(_state(plan))
    assert "전자발행 계산서가 없습니다" in out["error"]
    assert "조회 2회" in out["error"]  # 몇 번 눌러보고 0건이라 했는지 사유에 남긴다.


# ── close_budget_status_popup — 분할 확정 후 잔존 '예산현황' 창 정리 ──────────────
class _BudgetModalMouse:
    """클릭 1회 = 예산현황 창 1장 닫힘(ERP 동작 시뮬)."""

    def __init__(self, page: "_BudgetModalPage") -> None:
        self._page = page

    async def click(self, x, y):
        self._page.clicks.append((x, y))
        self._page.budget_left = max(0, self._page.budget_left - 1)


class _BudgetModalPage:
    """예산현황 창 n장 + (선택) 무관한 창 1장의 스냅샷/버튼 좌표를 돌려주는 page 스텁."""

    def __init__(self, budget_windows: int = 1, *, other_title: str | None = None,
                 buttons: tuple[str, ...] = ("확인", "취소")) -> None:
        self.budget_left = budget_windows
        self._other = other_title
        self._buttons = buttons
        self.clicks: list = []
        self.mouse = _BudgetModalMouse(self)

    def _windows(self) -> list[dict]:
        wins = [
            {"title": "예산현황", "text": "예산 배분", "buttons": list(self._buttons)}
            for _ in range(self.budget_left)
        ]
        if self._other:
            wins.append({"title": self._other, "text": "", "buttons": ["확인"]})
        return wins

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.MODALS_SNAPSHOT_JS:
            return self._windows()
        if js_src == js_lib.MODAL_BTN_BOX_JS:
            # 실물 MODAL_BTN_BOX_JS 와 동일하게 최상단 창부터 라벨 일치를 찾고 그 창 제목을 싣는다.
            win = next((w for w in reversed(self._windows()) if arg in w["buttons"]), None)
            return {"x": 5, "y": 5, "title": win["title"]} if win else None
        return None

    async def wait_for_timeout(self, ms):
        return None


async def test_close_budget_status_popup_noop_when_absent():
    # 비분할(PRE22) 경로처럼 창이 없으면 아무것도 클릭하지 않는다.
    page = _BudgetModalPage(budget_windows=0)
    out = await steps.close_budget_status_popup(page)
    assert out == {"ok": True, "closed": 0}
    assert page.clicks == []


async def test_close_budget_status_popup_closes_single():
    page = _BudgetModalPage(budget_windows=1)
    out = await steps.close_budget_status_popup(page)
    assert out == {"ok": True, "closed": 1}
    assert page.clicks == [(5, 5)]


async def test_close_budget_status_popup_closes_stacked_windows():
    page = _BudgetModalPage(budget_windows=2)
    out = await steps.close_budget_status_popup(page)
    assert out == {"ok": True, "closed": 2}
    assert page.budget_left == 0


async def test_close_budget_status_popup_fails_when_button_missing():
    # 확인/예/닫기 어느 라벨도 없으면 창을 못 닫는다 — 잔존을 감추지 않고 실패로 끊는다.
    page = _BudgetModalPage(budget_windows=1, buttons=("뒤로",))
    out = await steps.close_budget_status_popup(page)
    assert out["ok"] is False and "예산현황" in out["reason"]


async def test_close_budget_status_popup_ignores_other_popups():
    # 예산현황이 아닌 창(피커 등)은 이 스텝의 책임이 아니다 — 건드리지 않는다.
    page = _BudgetModalPage(budget_windows=0, other_title="프로젝트(WBS)")
    out = await steps.close_budget_status_popup(page)
    assert out == {"ok": True, "closed": 0}
    assert page.clicks == []


# ── fill_fund_item — 관리항목 '자금과목' 채움(브라우저 스텝, page 스텁) ──────────
class _FundPage:
    """자금과목 채움 시뮬 — 관리항목 패널 3종 JS + 팝업 개수(돋보기(10,10)=열림/적용(20,20)=닫힘)."""

    def __init__(self, *, panel_row: bool = True, readback: dict | None = None,
                 rows: list[dict] | None = None) -> None:
        self._panel_row = panel_row
        self._readback = readback if readback is not None else {"found": True, "code": "5310", "name": "일반경비"}
        self._rows = rows if rows is not None else [{"FUND_CD": "5310", "FUND_NM": "일반경비"}]
        self.clicks: list = []
        self.mouse = _FakeMouse(self.clicks)

    async def evaluate(self, js_src, arg=None):
        if js_src == steps._ROW_SCROLL_JS:
            return self._panel_row
        if js_src == steps._ROW_BUTTON_JS:
            return {"x": 10, "y": 10} if self._panel_row else None
        if js_src == steps._ROW_VALUES_JS:
            return self._readback
        if js_src == js_lib.POPUP_COUNT_JS:
            return 0 if (20, 20) in self.clicks or (10, 10) not in self.clicks else 1
        if js_src == ti_js.INVOICE_POPUP_DUMP_JS:
            return {"ok": True, "title": "자금과목(기표)", "grid": {"rows": self._rows}}
        if js_src == js_lib.PICKER_SELECT_JS:
            return {"ok": True}
        if js_src == js_lib.PICKER_APPLY_BTN_JS:
            return {"x": 20, "y": 20}
        if js_src == js_lib.MODALS_SNAPSHOT_JS:
            return []
        return None

    async def wait_for_timeout(self, ms):
        return None


class _FakeMouse:
    def __init__(self, sink: list) -> None:
        self._sink = sink

    async def click(self, x, y):
        self._sink.append((x, y))


@pytest.fixture
def _no_picker_search(monkeypatch):
    async def _noop(page, keyword):
        return None

    monkeypatch.setattr(steps, "_picker_search", _noop)


async def test_fill_fund_item_applies_default_and_reads_back(_no_picker_search):
    page = _FundPage()
    out = await steps.fill_fund_item(page)
    assert out == {"ok": True, "code": "5310", "name": "일반경비"}
    assert page.clicks == [(10, 10), (20, 20)]  # 돋보기 → 적용.


async def test_fill_fund_item_fails_when_readback_empty(_no_picker_search):
    # 적용은 했는데 패널 값이 비면 저장 반려로 이어진다 — 성공 단정 금지(세팅→독립확인).
    page = _FundPage(readback={"found": True, "code": "", "name": ""})
    out = await steps.fill_fund_item(page)
    assert out["ok"] is False
    assert "자금과목" in out["reason"]


async def test_fill_fund_item_fails_when_panel_row_missing(_no_picker_search):
    page = _FundPage(panel_row=False)
    out = await steps.fill_fund_item(page)
    assert out["ok"] is False and "자금과목" in out["reason"]
    assert page.clicks == []  # 행이 없으면 아무것도 클릭하지 않는다.


def test_map_split_plan_to_grid_by_note_then_order():
    plan = [{"note": "b"}, {"note": "a"}]
    grid = [{"NOTE_DC": "a"}, {"NOTE_DC": "b"}]
    assert steps.map_split_plan_to_grid(plan, grid) == [1, 0]
    # 중복 적요 — 순서 배정 폴백(전 행이 커버되면 된다).
    plan2 = [{"note": "x"}, {"note": "x"}]
    grid2 = [{"NOTE_DC": "x"}, {"NOTE_DC": "x"}]
    assert sorted(steps.map_split_plan_to_grid(plan2, grid2)) == [0, 1]
    # 행수 불일치 = 매핑 불가.
    assert steps.map_split_plan_to_grid(plan, grid[:1]) is None


# ══════════════════════════════════════════════════════════════════════════════
# 결의구분·그래프·등록·픽스처 lockstep
# ══════════════════════════════════════════════════════════════════════════════
def test_gubun_label_and_fg():
    assert TAX_INVOICE_GUBUN_LABEL == "세금계산서"
    assert TAX_INVOICE_FG_CODE == "51"


def test_graph_compiles():
    assert build_tax_invoice_graph() is not None


def test_registered_in_workflow_registry():
    import app.agents  # noqa: F401 — import 시 register_workflow 트리거

    from app.live.registry import get_spec

    spec = get_spec("tax-invoice")
    assert spec is not None
    assert spec.needs_browser is True
    assert spec.delay_scale == 0.4
    assert spec.site == "omnisol"


def test_fixture_promoted_lockstep():
    from app.services.agent_fixtures import AGENT_FIXTURES

    fx = next((f for f in AGENT_FIXTURES if f.get("id") == "tax-invoice"), None)
    assert fx is not None
    assert fx["workflow_id"] == "tax-invoice"
    assert fx["flow_graph"] is not None
    # 상신 수동 + 발행 후 실데이터 검증 미완 명시(handoff_note 계약).
    assert "상신" in fx["handoff_note"] and "직접" in fx["handoff_note"]
    assert "검증 미완" in fx["handoff_note"]
    # steps 의 key 순서 = build_tax_invoice_graph 노드 등록 순서(그래프와 lockstep).
    step_keys = [s["key"] for s in fx["steps"]]
    assert step_keys == [
        "validate_params",
        "login",
        "user_type",
        "menu_nav",
        "set_gubun",
        "add_row",
        "select_evdn",
        "pick_invoices",
        "apply_invoices",
        "fill_rows",
        "split_costs",
        "save_doc",
    ]
    # 그래프 노드 집합과도 일치(등록 누락/이름 드리프트 감시).
    graph_nodes = set(build_tax_invoice_graph().get_graph().nodes)
    assert set(step_keys) <= graph_nodes


# ══════════════════════════════════════════════════════════════════════════════
# 노드 단위(스텝 monkeypatch — 브라우저 없이 계약·분기 검증)
# ══════════════════════════════════════════════════════════════════════════════
class _FakePage:
    """노드는 조작을 steps 스텁에 위임 — page 는 최소 인터페이스만 제공한다."""

    async def evaluate(self, js_src, arg=None):
        return {"ok": True}

    async def wait_for_timeout(self, ms):
        return None


def _state(plan: dict, **over) -> dict:
    return {"events": asyncio.Queue(), "page": _FakePage(), "plan": plan, **over}


async def test_validate_node_success():
    node = make_validate_params_node()
    out = await node({"events": asyncio.Queue(), "params": _ti()})
    assert "error" not in out
    assert out["plan"]["evidence_code"] == "22"
    assert_keys_declared(TaxInvoiceState, out)


async def test_validate_node_korean_error():
    node = make_validate_params_node()
    out = await node({"events": asyncio.Queue(), "params": _ti(partner_name=None)})
    assert "거래처" in out["error"]


def _patch_modal_ready(monkeypatch, ok: bool = True):
    """발행 후 증빙 적용 뒤 계산서 모달 확인 — 열림/미열림 스텁."""

    async def fake_ready(page, **kw):
        return {"ok": ok, "grids": [{"gridIndex": 0, "n": 0, "rows": []}] if ok else [],
                "titles": ["공지"] if not ok else ["전자세금계산서/전자계산서"]}

    monkeypatch.setattr(evdn_mod.steps, "wait_invoice_popup_ready", fake_ready)


async def test_select_evdn_node_requires_invoice_modal_for_post(monkeypatch):
    """증빙 적용이 곧 리스트 모달을 연다 — 안 열리면 다음 스텝으로 새지 않고 단락한다."""

    async def fake_select(page, code, answer):
        return {"ok": True, "answered": answer, "picked_name": "세금계산서", "cell": "세금계산서"}

    monkeypatch.setattr(evdn_mod.steps, "select_evidence", fake_select)
    _patch_modal_ready(monkeypatch, ok=False)
    node = evdn_mod.make_select_evdn_node()
    post = parse_tax_invoice_params(
        _ti(issue="post", partner_name=None, supply_amount=None,
            budget_unit_name=None, project_wbs=None, note=None)
    )
    out = await node(_state(post))
    assert "계산서 모달이 열리지 않았습니다" in out["error"]
    # 발행 전은 모달을 요구하지 않는다.
    out_pre = await node(_state(parse_tax_invoice_params(_ti())))
    assert "error" not in out_pre


async def test_select_evdn_node_answers_by_path(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_select(page, code, answer):
        calls.append((code, answer))
        return {"ok": True, "answered": answer, "picked_name": "세금계산서", "cell": "세금계산서"}

    monkeypatch.setattr(evdn_mod.steps, "select_evidence", fake_select)
    _patch_modal_ready(monkeypatch)
    node = evdn_mod.make_select_evdn_node()
    pre = parse_tax_invoice_params(_ti())
    out = await node(_state(pre))
    assert "error" not in out
    post = parse_tax_invoice_params(_ti(issue="post", partner_name=None, supply_amount=None))
    await node(_state(post))
    split_manual = parse_tax_invoice_params(_split_ti())
    await node(_state(split_manual))
    split_auto = parse_tax_invoice_params(_split_ti(partner_name=None, supply_amount=None))
    await node(_state(split_auto))
    # 발행 전만 "아니요" — 수동분할(11)도 발행 후 계열이라 "예".
    assert calls == [("22", "아니요"), ("03", "예"), ("11", "예"), ("11", "예")]


async def test_select_evdn_node_fails_when_cell_not_reflected(monkeypatch):
    """증빙 셀 재독이 고른 항목명과 다르면 진행하지 않는다(다른 증빙 저장 방지)."""

    async def fake_select(page, code, answer):
        return {"ok": True, "answered": answer, "picked_name": "세금계산서(원증빙)", "cell": "세금계산서"}

    monkeypatch.setattr(evdn_mod.steps, "select_evidence", fake_select)
    _patch_modal_ready(monkeypatch)
    node = evdn_mod.make_select_evdn_node()
    out = await node(_state(parse_tax_invoice_params(_split_ti())))
    assert "반영되지 않았습니다" in out["error"]
    assert "세금계산서" in out["error"]


def _patch_fill_ok(monkeypatch, calls: list[str]):
    def _rec(name, extra=None):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, **(extra or {})}

        return _f

    monkeypatch.setattr(fill_mod.steps, "_fill_partner_cell", _rec("partner"))
    monkeypatch.setattr(fill_mod.steps, "set_row_note", _rec("note"))
    monkeypatch.setattr(fill_mod.steps, "fill_budget_by_name", _rec("budget"))
    monkeypatch.setattr(fill_mod.steps, "type_amount", _rec("amount"))
    monkeypatch.setattr(fill_mod.steps, "fill_project", _rec("project"))
    monkeypatch.setattr(fill_mod.steps, "fill_exempt_reason", _rec("exempt"))
    monkeypatch.setattr(fill_mod.doc_steps, "set_acct_date", _rec("acct_date"))
    monkeypatch.setattr(fill_mod.steps, "fill_fund_item", _rec("fund", {"name": "일반경비"}))


async def test_fill_node_pre_order(monkeypatch):
    calls: list[str] = []
    _patch_fill_ok(monkeypatch, calls)
    node = fill_mod.make_fill_rows_node()
    plan = parse_tax_invoice_params(_ti(actg_date="2026-08-14"))
    out = await node(_state(plan))
    assert out.get("filled") == 1
    assert calls == ["partner", "note", "budget", "amount", "project", "acct_date", "fund"]
    assert_keys_declared(TaxInvoiceState, out)


async def test_fill_node_skips_for_post(monkeypatch):
    # 발행 후 본문은 개입에서 받아 apply_invoices 가 행별로 채운다 — 이 노드는 손대지 않는다.
    calls: list[str] = []
    _patch_fill_ok(monkeypatch, calls)
    node = fill_mod.make_fill_rows_node()
    plan = parse_tax_invoice_params(
        _ti(issue="post", tax="exempt", partner_name=None, supply_amount=None,
            budget_unit_name=None, project_wbs=None, note=None)
    )
    out = await node(_state(plan))
    assert out == {} and calls == []


async def test_fill_node_fund_failure_blocks_save(monkeypatch):
    """자금과목 미채움은 저장 반려로 이어진다 — 채움 실패는 filled 없이 error 로 끊는다."""
    calls: list[str] = []
    _patch_fill_ok(monkeypatch, calls)

    async def bad_fund(*a, **k):
        return {"ok": False, "reason": "관리항목 패널에 '자금과목' 행이 없습니다"}

    monkeypatch.setattr(fill_mod.steps, "fill_fund_item", bad_fund)
    node = fill_mod.make_fill_rows_node()
    out = await node(_state(parse_tax_invoice_params(_ti())))
    assert "자금과목" in out["error"]
    assert "filled" not in out


async def test_fill_node_failure_short_circuits(monkeypatch):
    calls: list[str] = []
    _patch_fill_ok(monkeypatch, calls)

    async def bad_budget(*a, **k):
        return {"ok": False, "reason": "예산단위 '없는팀' 일치 없음"}

    monkeypatch.setattr(fill_mod.steps, "fill_budget_by_name", bad_budget)
    node = fill_mod.make_fill_rows_node()
    out = await node(_state(parse_tax_invoice_params(_ti())))
    assert "예산단위" in out["error"]
    assert "amount" not in calls  # 실패 이후 단락.


def _post_plan(**over):
    base = dict(issue="post", partner_name=None, supply_amount=None,
                budget_unit_name=None, project_wbs=None, note=None)
    base.update(over)
    return parse_tax_invoice_params(_ti(**base))


def _submit_row(no: int, *, skip: bool = False, budget: str = "임원실", note: str = "적요",
                wbs: str = "800") -> dict:
    return {
        "no": no,
        "skip": skip,
        "budgetUnit": {"code": "1000|계획|계정", "name": budget},
        "project": {"code": "PJT|800", "name": "공통", "wbsNo": wbs},
        "note": note,
    }


_POPUP_ROWS = [
    {"START_DT": "20260803", "PARTNER_NM": "노무법인", "PARTNER_CD": "10837",
     "SPPRC_AMT": 400_000, "VAT_AMT": "40,000", "SUM_AMT": 440_000,
     "NTS_APRVL_NO": "2026080312345678", "ITEM_NM": "자문료", "DATA_FG_NM": "전자세금계산서"},
    {"START_DT": "2026-08-05", "PARTNER_NM": "세무법인", "SPPRC_AMT": 100_000,
     "VAT_AMT": 10_000, "SUM_AMT": 110_000, "NTS_APRVL_NO": "2026080587654321"},
]


def _patch_pick(monkeypatch, resp: dict, rows: list[dict] | None = None) -> list[dict]:
    frames: list[dict] = []

    async def fake_open(page, f, t):
        return {"ok": True, "rows": list(rows if rows is not None else _POPUP_ROWS), "settled": True}

    async def fake_hitl(events, **kw):
        frames.append(kw)
        return resp

    async def fake_catalogs(owner):
        return {"favorites": [{"code": "1000|a|b", "name": "임원실"}], "mine": []}, [{"code": "PJT|800", "name": "공통"}]

    monkeypatch.setattr(pick_mod.steps, "open_invoice_list", fake_open)
    monkeypatch.setattr(pick_mod, "wait_hitl", fake_hitl)
    monkeypatch.setattr(pick_mod, "load_catalogs", fake_catalogs)
    return frames


def test_invoice_grid_row_payload():
    """프레임 행 = InvoiceGridRow(types.ts:100-116) — 날짜 정규화·금액 정수화."""
    row = pick_mod.invoice_grid_row(0, _POPUP_ROWS[0])
    assert row == {
        "no": 1, "invoiceDate": "2026-08-03", "partnerName": "노무법인", "partnerCode": "10837",
        "supplyAmount": 400_000, "taxAmount": 40_000, "sumAmount": 440_000,
        "ntsAprvlNo": "2026080312345678", "itemName": "자문료", "dataKind": "전자세금계산서",
    }
    bare = pick_mod.invoice_grid_row(4, {})
    assert bare["no"] == 5 and bare["supplyAmount"] is None and bare["partnerName"] == ""


def test_parse_invoice_submission_rules():
    """선택 = skip:false(runs.py GridRowIn). 선택 행은 예산단위·적요 필수, 범위 밖은 무시."""
    resp = {"rows": [_submit_row(2), _submit_row(1, skip=True), _submit_row(9)]}
    sel, err = pick_mod.parse_invoice_submission(resp, 2)
    assert err is None and [s["no"] for s in sel] == [2]  # 1=제외, 9=범위 밖.
    assert sel[0]["index"] == 1 and sel[0]["budget_unit_name"] == "임원실" and sel[0]["project_wbs"] == "800"
    _, err = pick_mod.parse_invoice_submission({"rows": [_submit_row(1, budget="")]}, 2)
    assert err and "예산단위" in err
    _, err = pick_mod.parse_invoice_submission({"rows": [_submit_row(1, note="  ")]}, 2)
    assert err and "적요" in err
    assert pick_mod.parse_invoice_submission({}, 2) == ([], None)


def test_parse_split_plan_rules():
    ok = {"splitPlan": [
        {"note": "행1", "amount": 42_000, "costCenter": "경영지원팀", "projectWbs": "800"},
        {"note": "행2", "amount": None, "costCenter": "개발팀", "projectWbs": "800"},
    ]}
    rows, err = pick_mod.parse_split_plan(ok)
    assert err is None
    assert rows == [
        {"note": "행1", "amount": 42_000, "cost_center": "경영지원팀", "project_wbs": "800"},
        {"note": "행2", "amount": None, "cost_center": "개발팀", "project_wbs": "800"},
    ]
    bad = {"splitPlan": [
        {"note": "행1", "amount": None, "costCenter": "A", "projectWbs": "800"},
        {"note": "행2", "amount": 1, "costCenter": "B", "projectWbs": "800"},
    ]}
    _, err = pick_mod.parse_split_plan(bad)
    assert err and "마지막 행" in err
    _, err = pick_mod.parse_split_plan({"splitPlan": [{"note": "", "amount": 1, "costCenter": "A", "projectWbs": "8"}]})
    assert err and "적요" in err


async def test_pick_invoices_node_skips_for_pre():
    node = pick_mod.make_pick_invoices_node()
    out = await node(_state(parse_tax_invoice_params(_ti())))
    assert out == {}


async def test_pick_invoices_node_emits_invoice_grid_frame(monkeypatch):
    frames = _patch_pick(monkeypatch, {"rows": [_submit_row(1), _submit_row(2, skip=True)]})
    node = pick_mod.make_pick_invoices_node()
    out = await node(_state(_post_plan()))
    # 프레임 계약(types.ts:242-267): kind·invoiceRows·split·budgetUnits·projects.
    assert frames[0]["kind"] == "invoice-grid"
    extra = frames[0]["extra"]
    assert [r["no"] for r in extra["invoiceRows"]] == [1, 2]
    assert extra["split"] is False
    assert extra["budgetUnits"]["favorites"][0]["name"] == "임원실"
    assert extra["projects"]["favorites"][0]["code"] == "PJT|800"
    # 응답 파싱 결과가 다음 노드 계약으로 나온다.
    assert out["invoice_picked"] == [0]
    assert out["invoice_selection"][0]["note"] == "적요"
    assert out["invoice_selection"][0]["grid_row"]["partnerName"] == "노무법인"
    assert out["split_plan"] == []
    assert_keys_declared(TaxInvoiceState, out)


async def test_pick_invoices_node_carries_split_plan(monkeypatch):
    resp = {
        "rows": [_submit_row(1)],
        "splitPlan": [
            {"note": "행1", "amount": 42_000, "costCenter": "경영지원팀", "projectWbs": "800"},
            {"note": "행2", "amount": None, "costCenter": "개발팀", "projectWbs": "800"},
        ],
    }
    frames = _patch_pick(monkeypatch, resp)
    node = pick_mod.make_pick_invoices_node()
    out = await node(_state(_post_plan(split=True, split_rows=None)))
    assert frames[0]["extra"]["split"] is True
    assert [r["cost_center"] for r in out["split_plan"]] == ["경영지원팀", "개발팀"]


async def test_pick_invoices_node_split_rejects_multi_selection(monkeypatch):
    resp = {
        "rows": [_submit_row(1), _submit_row(2)],
        "splitPlan": [
            {"note": "행1", "amount": 42_000, "costCenter": "A", "projectWbs": "800"},
            {"note": "행2", "amount": None, "costCenter": "B", "projectWbs": "800"},
        ],
    }
    _patch_pick(monkeypatch, resp)
    node = pick_mod.make_pick_invoices_node()
    out = await node(_state(_post_plan(split=True, split_rows=None)))
    assert "1건만" in out["error"]


async def test_pick_invoices_node_surfaces_missing_row_input(monkeypatch):
    _patch_pick(monkeypatch, {"rows": [_submit_row(1, note="")]})
    node = pick_mod.make_pick_invoices_node()
    out = await node(_state(_post_plan()))
    assert "적요" in out["error"]


async def test_pick_invoices_node_empty_selection_aborts(monkeypatch):
    _patch_pick(monkeypatch, {"rows": [_submit_row(1, skip=True)]})
    node = pick_mod.make_pick_invoices_node()
    out = await node(_state(_post_plan()))
    assert out.get("aborted") is True
    assert "저장하지 않고" in out["result"]
    assert_keys_declared(TaxInvoiceState, out)


async def test_pick_invoices_node_reports_empty_period(monkeypatch):
    async def fake_open(page, f, t):
        return {"ok": True, "rows": [], "settled": True, "attempts": 2}

    monkeypatch.setattr(pick_mod.steps, "open_invoice_list", fake_open)
    node = pick_mod.make_pick_invoices_node()
    out = await node(_state(_post_plan()))
    assert "전자발행 계산서가 없습니다" in out["error"] and "조회 2회" in out["error"]


# ── apply_invoices — 적용 + 행별 채움(1건 확정 / 복수 순차 ❓) ─────────────────────
def _patch_apply(monkeypatch, calls: list[str], rowcounts: list[int]):
    def _rec(name, extra=None):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, **(extra or {})}

        return _f

    counts = iter(rowcounts)

    class _P(_FakePage):
        async def evaluate(self, js_src, arg=None):
            try:
                return next(counts)
            except StopIteration:
                return rowcounts[-1]

    monkeypatch.setattr(apply_mod.steps, "apply_invoice_rows", _rec("apply"))
    monkeypatch.setattr(apply_mod.steps, "set_row_note", _rec("note"))
    monkeypatch.setattr(apply_mod.steps, "fill_budget_by_name", _rec("budget"))
    monkeypatch.setattr(apply_mod.steps, "fill_project", _rec("project"))
    monkeypatch.setattr(apply_mod.steps, "fill_exempt_reason", _rec("exempt"))
    monkeypatch.setattr(apply_mod.steps, "fill_fund_item", _rec("fund", {"name": "일반경비"}))
    monkeypatch.setattr(apply_mod.steps, "open_invoice_list", _rec("reopen", {"rows": _POPUP_ROWS}))
    return _P()


def _sel(no: int, **over) -> dict:
    base = {
        "no": no, "index": no - 1, "budget_unit_name": "임원실", "budget_unit_code": "1000",
        "project_wbs": "800", "project_name": "공통", "note": f"적요{no}",
        "grid_row": {"ntsAprvlNo": _POPUP_ROWS[no - 1].get("NTS_APRVL_NO"), "partnerName": ""},
    }
    base.update(over)
    return base


async def test_apply_invoices_node_single_row_sequence(monkeypatch):
    calls: list[str] = []
    page = _patch_apply(monkeypatch, calls, [0, 1])
    node = apply_mod.make_apply_invoices_node()
    out = await node({**_state(_post_plan()), "page": page, "invoice_selection": [_sel(1)]})
    assert out.get("filled") == 1
    assert calls == ["apply", "note", "budget", "project", "fund"]
    assert_keys_declared(TaxInvoiceState, out)


async def test_apply_invoices_node_multi_rows_are_sequential(monkeypatch):
    # ❓ 복수 적용 구조 미실측 — 1건씩 적용하고 2건째는 재조회+승인번호 재매칭으로 잡는다.
    calls: list[str] = []
    page = _patch_apply(monkeypatch, calls, [0, 1, 1, 2])
    node = apply_mod.make_apply_invoices_node()
    out = await node({**_state(_post_plan()), "page": page, "invoice_selection": [_sel(1), _sel(2)]})
    assert out.get("filled") == 1
    assert calls == [
        "apply", "note", "budget", "project", "fund",
        "reopen", "apply", "note", "budget", "project", "fund",
    ]


async def test_apply_invoices_node_fails_when_detail_row_not_created(monkeypatch):
    # 적용 후 상세 행이 안 늘면 다음 채움이 엉뚱한 행을 친다 — 그 자리에서 끊는다.
    calls: list[str] = []
    page = _patch_apply(monkeypatch, calls, [1, 1])
    node = apply_mod.make_apply_invoices_node()
    out = await node({**_state(_post_plan()), "page": page, "invoice_selection": [_sel(1)]})
    assert "상세 행이 늘지 않았습니다" in out["error"]
    assert "note" not in calls


async def test_apply_invoices_node_exempt_reason_row(monkeypatch):
    calls: list[str] = []
    page = _patch_apply(monkeypatch, calls, [0, 1])
    node = apply_mod.make_apply_invoices_node()
    plan = _post_plan(tax="exempt")
    out = await node({**_state(plan), "page": page, "invoice_selection": [_sel(1)]})
    assert out.get("filled") == 1
    assert calls == ["apply", "note", "budget", "project", "exempt", "fund"]


async def test_apply_invoices_node_skips_for_pre():
    node = apply_mod.make_apply_invoices_node()
    out = await node(_state(parse_tax_invoice_params(_ti())))
    assert out == {}


def test_match_invoice_index_by_approval_then_partner():
    rows = [{"NTS_APRVL_NO": "A2", "PARTNER_NM": "세무법인", "SUM_AMT": 110_000}]
    assert apply_mod.match_invoice_index(rows, {"ntsAprvlNo": "A2"}) == 0
    assert apply_mod.match_invoice_index(rows, {"partnerName": "세무법인", "sumAmount": 110_000}) == 0
    assert apply_mod.match_invoice_index(rows, {"ntsAprvlNo": "없음"}) is None


async def test_split_node_uses_hitl_split_plan(monkeypatch):
    """발행 후 분할은 개입(splitPlan)이 원천 — plan.split_rows 가 비어도 실행된다."""
    calls: list[str] = []

    def _rec(name, extra=None):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, **(extra or {})}

        return _f

    grid = [{"NOTE_DC": "행1", "SPPRC_AMT2": 42_000}, {"NOTE_DC": "행2", "SPPRC_AMT2": 42_000}]

    async def fake_dump(page):
        return grid

    for name in ("open_split_popup", "add_split_row", "set_split_note", "set_split_amount",
                 "select_split_row", "delete_split_row", "fill_split_picker", "confirm_split_apply"):
        monkeypatch.setattr(split_mod.steps, name, _rec(name))
    monkeypatch.setattr(split_mod.steps, "apply_balance", _rec("apply_balance", {"rows": grid}))
    monkeypatch.setattr(split_mod.steps, "dump_split_rows", fake_dump)
    monkeypatch.setattr(split_mod.steps, "close_budget_status_popup", _rec("budget_status", {"closed": 0}))

    plan = _post_plan(split=True, split_rows=None)
    split_plan = [
        {"note": "행1", "amount": 42_000, "cost_center": "A", "project_wbs": "800"},
        {"note": "행2", "amount": None, "cost_center": "B", "project_wbs": "800"},
    ]
    node = split_mod.make_split_costs_node()
    out = await node({**_state(plan), "split_plan": split_plan})
    assert out.get("split_done") is True
    assert calls[0] == "open_split_popup" and "confirm_split_apply" in calls


async def test_split_node_skips_when_not_split():
    node = split_mod.make_split_costs_node()
    out = await node(_state(parse_tax_invoice_params(_ti())))
    assert out == {}


async def test_split_node_full_recipe(monkeypatch):
    calls: list[str] = []
    grid_after_balance = [
        {"NOTE_DC": "분할행1", "SPPRC_AMT2": 42_000},
        {"NOTE_DC": "분할행2", "SPPRC_AMT2": None},  # 더미(고아).
        {"NOTE_DC": None, "SPPRC_AMT2": 42_000},  # 차액반영 잔액행.
    ]
    grid_final = [
        {"NOTE_DC": "분할행1", "SPPRC_AMT2": 42_000},
        {"NOTE_DC": "분할행2", "SPPRC_AMT2": 42_000},
    ]
    dumps = iter([grid_after_balance, grid_final])

    def _rec(name, extra=None):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, **(extra or {})}

        return _f

    async def fake_dump(page):
        try:
            return next(dumps)
        except StopIteration:
            return grid_final

    monkeypatch.setattr(split_mod.steps, "open_split_popup", _rec("open"))
    monkeypatch.setattr(split_mod.steps, "add_split_row", _rec("add"))
    monkeypatch.setattr(split_mod.steps, "set_split_note", _rec("note"))
    monkeypatch.setattr(split_mod.steps, "set_split_amount", _rec("amount"))
    monkeypatch.setattr(split_mod.steps, "select_split_row", _rec("select"))
    monkeypatch.setattr(split_mod.steps, "apply_balance", _rec("balance", {"rows": grid_after_balance}))
    monkeypatch.setattr(split_mod.steps, "delete_split_row", _rec("delete"))
    monkeypatch.setattr(split_mod.steps, "dump_split_rows", fake_dump)
    monkeypatch.setattr(split_mod.steps, "fill_split_picker", _rec("picker"))
    monkeypatch.setattr(split_mod.steps, "confirm_split_apply", _rec("apply"))
    monkeypatch.setattr(split_mod.steps, "close_budget_status_popup", _rec("budget", {"closed": 1}))

    node = split_mod.make_split_costs_node()
    out = await node(_state(parse_tax_invoice_params(_split_ti())))
    assert out.get("split_done") is True
    # 확정 레시피 골격: 행1(추가·적요·금액) → 더미(추가·적요) → 선택 → 차액반영 → 잔액행 적요
    # → 잉여 삭제 → 전 행 CC·PJT(행당 picker 2회) → 적용 → 잔존 '예산현황' 창 정리.
    # 상대계정(FEOTH)은 저장 시 자동 파생이라 채우지 않는다(편집 위젯 없음 — headed 세션 확정).
    assert calls == [
        "open", "add", "note", "amount", "add", "note", "select", "balance", "note",
        "delete", "picker", "picker", "picker", "picker", "apply", "budget",
    ]
    assert_keys_declared(TaxInvoiceState, out)


async def test_save_node_gates_when_nothing_filled():
    node = make_save_doc_node()
    out = await node({"events": asyncio.Queue(), "page": _FakePage(), "filled": 0})
    assert "저장하지 않았습니다" in out["result"]


async def test_save_node_skips_when_aborted():
    node = make_save_doc_node()
    out = await node({"events": asyncio.Queue(), "page": _FakePage(), "aborted": True, "filled": 1})
    assert out == {}


async def test_save_node_surfaces_rejection_reason(monkeypatch):
    from app.agents.tax_invoice.nodes import save as save_mod

    async def fake_save(page, confirm):
        assert confirm is True
        return {"ok": False, "reason": "저장(F7)이 검증 실패로 거부됨: 공급가액(거래금액)이 입력되지 않았습니다."}

    async def fake_shield(fn, **kw):
        return await fn()

    class _P(_FakePage):
        async def evaluate(self, js_src, arg=None):
            if "k-window" in js_src:  # POPUP_COUNT_JS — F7 사전 조건.
                return 0
            return True

    monkeypatch.setattr(save_mod.card_steps, "save_document", fake_save)
    monkeypatch.setattr(save_mod, "shielded_commit", fake_shield)
    node = make_save_doc_node()
    out = await node({"events": asyncio.Queue(), "page": _P(), "filled": 1, "plan": {}})
    assert "거부됨" in out["error"]
    assert "공급가액(거래금액)이 입력되지 않았습니다" in out["error"]  # 반려 사유 그대로 노출.


# ── 증빙 적용 직후 창 분류(실런 f2270bb3: 03 리스트 팝업을 미지 다이얼로그로 오인 중단) ──
def test_classify_post_apply_invoice_popup_is_not_dialog():
    # 03: 적용 직후 유일한 k-window = 계산서 리스트 팝업(본문 미렌더 → text 비어 title 폴백)
    modals = [{"title": "전자세금계산서/전자계산서", "text": "", "buttons": []}]
    assert steps.classify_post_apply_modals(modals) == ("popup", [])


def test_classify_post_apply_gate_dialog_detected():
    modals = [{"title": "", "text": "전자발행된 증빙으로 입력하시겠습니까?", "buttons": ["예", "아니요"]}]
    kind, texts = steps.classify_post_apply_modals(modals)
    assert kind == "dialog" and steps.GATE_DIALOG_HINT in texts[0]


def test_classify_post_apply_unknown_window_is_dialog():
    modals = [
        {"title": "전자세금계산서/전자계산서", "text": "", "buttons": []},
        {"title": "알림", "text": "예산이 초과되었습니다", "buttons": ["확인"]},
    ]
    kind, texts = steps.classify_post_apply_modals(modals)
    assert kind == "dialog" and texts == ["예산이 초과되었습니다"]


def test_classify_post_apply_none():
    assert steps.classify_post_apply_modals([]) == ("none", [])
    assert steps.classify_post_apply_modals(None) == ("none", [])
