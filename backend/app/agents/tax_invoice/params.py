"""세금계산서 실행 전 폼 파라미터 — 증빙유형 도출(evidence_for) + 정규화/검증.

`params["tax_invoice"]` 가 단일 계약(백엔드·프론트 공유)이다. 증빙유형 코드는 **서버가
도출**한다: `evidence_for(issue, split, tax, nondeduct_reason)` — 프론트 시뮬레이션
`src/components/live/simulation/tax-invoice/model.ts` 의 `evidenceFor` 와 동일 매핑이어야
한다(패리티 테스트가 QUICK_PICK_GROUPS 리터럴로 드리프트를 감시한다).

불변식(PROCESS.md D4): 불공×분할 조합 없음 · 발행 전 분할 불가 · 발행 전 불공은 24 하나
(사유 무구분). 위반과 입력 누락은 전부 **한국어 ValueError** 로 던진다(그래프 진입 노드가
{"error": ...} 로 단락).

분할 금액(D7): 금액이 단일 원천이며 **마지막 행 amount=null = 차액반영으로 잔액 흡수**.
금액 산술은 Decimal + ROUND_HALF_UP (내장 round() 금지).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# ── 증빙유형 매핑(D4 — 프론트 model.ts EVIDENCE_LABEL 미러) ──────────────────
EVIDENCE_LABEL: dict[str, str] = {
    "03": "세금계산서",
    "04": "계산서",
    "05": "세금계산서(불공) 사업과 관련없는 지출",
    "06": "세금계산서(불공) 비영업용소형승용차구입, 유지 및 임차",
    "07": "세금계산서(불공) 면세사업과 관련된분",
    "11": "세금계산서(원증빙)",
    "13": "계산서(원증빙)",
    "22": "세금계산서 발행 전 입력(과세)",
    "23": "세금계산서 발행 전 입력(비과세)",
    "24": "세금계산서 발행 전 (과세)불공 차량용",
}

_ISSUE_VALUES = ("pre", "post")
_TAX_VALUES = ("taxable", "exempt", "nondeduct")
# 발행 후 불공 사유 → 코드(05/06/07). 발행 전 불공은 사유 무구분 24 하나(D4).
_NONDEDUCT_CODE: dict[str, str] = {"none_biz": "05", "car": "06", "exempt_biz": "07"}

# 분할 행 수 한계(계약: 2~20행) · 적요 최대 길이.
SPLIT_ROWS_MIN = 2
SPLIT_ROWS_MAX = 20
NOTE_MAX_LEN = 200

# 비과세 사유구분 기본값(D8).
DEFAULT_EXEMPT_REASON = "일반면세"


def evidence_for(
    issue: str, split: bool, tax: str, nondeduct_reason: str | None
) -> str:
    """답 조합 → 증빙유형 코드(10종). 불변식 위반은 한국어 ValueError.

    프론트 `evidenceFor` 와 동일 매핑(패리티 테스트로 강제): 발행 전 불공은 사유와 무관하게
    24 하나이며, 발행 후 불공은 사유까지 골라야 코드(05/06/07)가 정해진다.
    """
    if issue not in _ISSUE_VALUES:
        raise ValueError(f"발행 전/후(issue) 값이 올바르지 않습니다: {issue!r} (pre/post)")
    if tax not in _TAX_VALUES:
        raise ValueError(f"과세여부(tax) 값이 올바르지 않습니다: {tax!r} (taxable/exempt/nondeduct)")
    if split and tax == "nondeduct":
        raise ValueError("불공 증빙은 비용분할과 함께 쓸 수 없습니다(불공×분할 조합 없음).")
    if issue == "pre":
        if split:
            raise ValueError("발행 전에는 비용분할을 할 수 없습니다(발행 전 분할 불가).")
        return {"taxable": "22", "exempt": "23", "nondeduct": "24"}[tax]
    if split:
        return "11" if tax == "taxable" else "13"
    if tax == "taxable":
        return "03"
    if tax == "exempt":
        return "04"
    code = _NONDEDUCT_CODE.get(nondeduct_reason or "")
    if not code:
        raise ValueError(
            "발행 후 불공은 사유(nondeduct_reason: none_biz/car/exempt_biz)를 골라야 합니다."
        )
    return code


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────
def _as_int(value: object, what: str) -> int:
    """정수 강제(bool 배제) — 금액 필드 공용. 실패는 한국어 ValueError."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what}은(는) 정수여야 합니다: {value!r}")
    return value


def _parse_date(value: object, what: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} 날짜 형식이 올바르지 않습니다(YYYY-MM-DD): {value!r}") from exc


def _require_text(value: object, what: str, *, max_len: int | None = None) -> str:
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"{what}이(가) 없습니다.")
    if max_len is not None and len(s) > max_len:
        raise ValueError(f"{what}은(는) 최대 {max_len}자입니다(현재 {len(s)}자).")
    return s


def resolve_split_amounts(
    supply_amount: int | None, amounts: list[int | None]
) -> tuple[list[int | None], bool]:
    """분할 행 금액 확정 — (확정 금액 리스트, 마지막 행 차액반영 여부) 반환.

    규칙(D7 + 계약): null 은 **마지막 행에만** 허용(= 차액반영으로 잔액 흡수). 전 행 명시면
    합계가 공급가액과 정확히 일치해야 한다. 산술은 Decimal + ROUND_HALF_UP(내장 round 금지).

    supply_amount=None(발행 후 행 선택 HITL 이후에야 총액이 정해지는 자동분할)은 총액 검증이
    불가하므로 **마지막 행 차액반영이 필수**이고, 잔액은 계산하지 않는다(마지막 amount=None 유지
    — ERP 차액반영 버튼이 흡수).
    """
    if not (SPLIT_ROWS_MIN <= len(amounts) <= SPLIT_ROWS_MAX):
        raise ValueError(
            f"분할 행은 {SPLIT_ROWS_MIN}~{SPLIT_ROWS_MAX}행이어야 합니다(현재 {len(amounts)}행)."
        )
    for i, a in enumerate(amounts[:-1]):
        if a is None:
            raise ValueError(f"분할 금액 비움(차액반영)은 마지막 행에만 허용됩니다(행 {i + 1}).")
    explicit = [a for a in amounts if a is not None]
    fixed: list[int] = []
    for i, a in enumerate(explicit):
        v = _as_int(a, f"분할 {i + 1}행 금액")
        if v == 0:
            raise ValueError(f"분할 {i + 1}행 금액이 0원입니다.")
        fixed.append(v)
    if supply_amount is None:
        if amounts[-1] is not None:
            raise ValueError(
                "공급가액 없이(발행 후 계산서 행 선택) 분할하려면 마지막 행은 차액반영(금액 비움)이어야 합니다."
            )
        return [*fixed, None], True
    total = Decimal(supply_amount)
    used = sum((Decimal(v) for v in fixed), Decimal(0))
    if amounts[-1] is None:
        # 마지막 행 = 차액(잔액) 흡수. Decimal 로 계산 후 원 단위 ROUND_HALF_UP 확정.
        remainder = (total - used).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if remainder == 0:
            raise ValueError(
                "분할 차액이 0원입니다 — 마지막 행 금액을 직접 입력하거나 앞 행 금액을 조정하세요."
            )
        return [*fixed, int(remainder)], True
    if used != total:
        raise ValueError(
            f"분할 금액 합계({int(used):,}원)가 공급가액({supply_amount:,}원)과 다릅니다."
        )
    return fixed, False


def _default_period() -> tuple[str, str]:
    """발행 후 조회기간 기본값 — 이번 달 1일 ~ 오늘(계약 기본값)."""
    today = date.today()
    return today.replace(day=1).isoformat(), today.isoformat()


# ── 정규화(그래프 validate 노드가 소비할 plan) ────────────────────────────────
def parse_tax_invoice_params(params: dict) -> dict:
    """`params["tax_invoice"]` → 정규화 plan(dict). 모든 실패는 한국어 ValueError.

    plan 키: issue·tax·split·split_manual·nondeduct_reason·evidence_code·evidence_label·
    partner_name·supply_amount·budget_unit_name·project_wbs·note·actg_date_compact·
    period_from/period_to·exempt_reason·split_rows([{note, amount:int|None, cost_center,
    project_wbs}] — amount None 은 자동분할 마지막 행=차액반영)·split_balance_last.
    """
    ti = params.get("tax_invoice")
    if not isinstance(ti, dict):
        raise ValueError("세금계산서 입력(tax_invoice)이 없습니다.")

    issue = str(ti.get("issue") or "")
    tax = str(ti.get("tax") or "")
    split = bool(ti.get("split"))
    nd_raw = ti.get("nondeduct_reason")
    nondeduct_reason = str(nd_raw) if nd_raw else None
    if nondeduct_reason is not None and nondeduct_reason not in _NONDEDUCT_CODE:
        raise ValueError(
            f"불공 사유(nondeduct_reason) 값이 올바르지 않습니다: {nondeduct_reason!r} "
            "(none_biz/car/exempt_biz)"
        )
    if tax != "nondeduct":
        nondeduct_reason = None  # 불공이 아니면 사유는 의미 없음(프론트 미전송 계약).
    if issue == "pre":
        nondeduct_reason = None  # 발행 전 불공은 사유 무구분(코드 24 하나 — D4).

    # 증빙유형 도출 — 불변식(불공×분할·발행 전 분할·발행 후 불공 사유 필수)은 여기서 걸린다.
    code = evidence_for(issue, split, tax, nondeduct_reason)

    # 발행 후(D1 2026-08-20 재확정)는 적요·예산단위·프로젝트를 **폼에서 받지 않는다** —
    # 계산서 행마다 달라 라이브 개입(kind="invoice-grid")에서 행별로 받는다. 프론트도 null 을
    # 보낸다(src/components/live/pre-run/tax-invoice-pre-run-form.tsx:243-246).
    if issue == "post":
        note = str(ti.get("note") or "").strip()
        budget_unit_name = str(ti.get("budget_unit_name") or "").strip()
        project_wbs = str(ti.get("project_wbs") or "").strip()
    else:
        note = _require_text(ti.get("note"), "적요(note)", max_len=NOTE_MAX_LEN)
        budget_unit_name = _require_text(ti.get("budget_unit_name"), "예산단위(budget_unit_name)")
        project_wbs = _require_text(ti.get("project_wbs"), "프로젝트(project_wbs)")

    # 거래처·공급가액 — 발행 전 필수(계약). 분할은 두 모드가 있다:
    #   * 수동분할(둘 다 제공): 계산서 조회 없이 직접 채우는 레시피 — 쓰기 프로브 검증 경로.
    #   * 자동분할(둘 다 없음): 발행 후 계산서 행 선택(HITL)이 거래처·공급가액을 채운 뒤 분할.
    # 어느 쪽이든 '비용분할' 버튼 전제조건(거래처·공급가액 채움 — PROCESS.md 실측)은 충족된다.
    partner_name = str(ti.get("partner_name") or "").strip() or None
    supply_amount: int | None = None
    if ti.get("supply_amount") is not None:
        supply_amount = _as_int(ti.get("supply_amount"), "공급가액(supply_amount)")
        if supply_amount == 0:
            raise ValueError("공급가액이 0원입니다.")
    if issue == "pre":
        if not partner_name:
            raise ValueError("발행 전에는 거래처(partner_name)가 필요합니다 — ERP 등록 정확명으로 입력하세요.")
        if supply_amount is None:
            raise ValueError("발행 전에는 공급가액(supply_amount)이 필요합니다.")
    split_manual = False
    if split:
        if (partner_name is None) != (supply_amount is None):
            raise ValueError(
                "비용분할을 직접 채우려면 거래처(partner_name)와 공급가액(supply_amount)을 함께 입력하세요"
                " — 발행 후 계산서 행 선택으로 진행하려면 둘 다 비웁니다."
            )
        split_manual = supply_amount is not None
        if split_manual and supply_amount is not None and supply_amount <= 0:
            raise ValueError("비용분할은 공급가액 합계가 0보다 커야 합니다(취소분 상계 총액 0 불가).")

    # 발행 후 조회기간(D5) — 기본 이번 달 1일~오늘.
    period_from: str | None = None
    period_to: str | None = None
    if issue == "post":
        df_from, df_to = _default_period()
        period_from = str(ti.get("period_from") or df_from)
        period_to = str(ti.get("period_to") or df_to)
        d_from = _parse_date(period_from, "조회 시작일(period_from)")
        d_to = _parse_date(period_to, "조회 종료일(period_to)")
        if d_from > d_to:
            raise ValueError(f"조회기간이 뒤집혔습니다: {period_from} ~ {period_to}")

    # 회계일(D9) — 발행 전 폼 입력(선택). 발행 후는 선택 행 마지막 계산서일 자동이라 미사용.
    actg_date_compact: str | None = None
    if issue == "pre" and ti.get("actg_date"):
        actg_date_compact = _parse_date(ti.get("actg_date"), "회계일(actg_date)").strftime("%Y%m%d")

    # 비과세 사유구분(D8) — 비과세일 때만, 기본 '일반면세'.
    exempt_reason: str | None = None
    if tax == "exempt":
        exempt_reason = str(ti.get("exempt_reason") or DEFAULT_EXEMPT_REASON).strip()

    # 분할 계획(D7) — 행별 적요·비용센터·프로젝트 필수(전 행 채워야 '적용'이 닫힌다 — 실측).
    split_rows: list[dict] = []
    split_balance_last = False
    # 발행 후 분할 계획도 개입(splitPlan)에서 받는다 — 폼이 보내면(구클라·발행 전 경로)
    # 그때만 여기서 정규화한다. 개입 계획의 검증은 pick_invoices 노드가 한다.
    raw_rows = ti.get("split_rows")
    if split and isinstance(raw_rows, list) and raw_rows:
        amounts: list[int | None] = []
        for i, r in enumerate(raw_rows):
            if not isinstance(r, dict):
                raise ValueError(f"분할 {i + 1}행 형식이 올바르지 않습니다.")
            amounts.append(None if r.get("amount") is None else _as_int(r.get("amount"), f"분할 {i + 1}행 금액"))
        fixed, split_balance_last = resolve_split_amounts(supply_amount, amounts)
        for i, (r, amt) in enumerate(zip(raw_rows, fixed)):
            split_rows.append(
                {
                    "note": _require_text(r.get("note"), f"분할 {i + 1}행 적요", max_len=NOTE_MAX_LEN),
                    "amount": amt,
                    "cost_center": _require_text(r.get("cost_center"), f"분할 {i + 1}행 비용센터"),
                    "project_wbs": _require_text(r.get("project_wbs"), f"분할 {i + 1}행 프로젝트"),
                }
            )

    return {
        "issue": issue,
        "tax": tax,
        "split": split,
        "split_manual": split_manual,
        "nondeduct_reason": nondeduct_reason,
        "evidence_code": code,
        "evidence_label": EVIDENCE_LABEL[code],
        "partner_name": partner_name,
        "supply_amount": supply_amount,
        "budget_unit_name": budget_unit_name,
        "project_wbs": project_wbs,
        "note": note,
        "actg_date_compact": actg_date_compact,
        "period_from": period_from,
        "period_to": period_to,
        "exempt_reason": exempt_reason,
        "split_rows": split_rows,
        "split_balance_last": split_balance_last,
    }
