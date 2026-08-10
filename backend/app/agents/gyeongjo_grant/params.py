"""경조금신청서 실행 전 폼 파라미터 — pydantic 단건 스키마 + 공급가액 계산 + 정규화.

국내/해외출장과 실행 방식은 같으나(모든 입력이 사용자 제공 → 실행 전 폼) **단건(1행)**이다:
경조사 1건 = 결의서 1장. 입력은 배열(rows[])이 아니라 단일 객체(`params["gyeongjo"]`).

- 공급가액(거래금액)은 **백엔드가 계산한다**(D10-a): `supply_amount` 가 근속 1년 미만이면
  정액의 50%(원 단위 반올림), 아니면 정액 그대로. 계산 위치는 이 모듈(국내출장 유류비 계산과
  동일 자리)이고, 정규화된 행의 amount 에 확정값을 싣는다.
- 회계일자(ACTG_DT)는 **증빙일자 = 사용자 입력** 그대로다(단건이라 max 파생 불필요, D4).
- 모든 검증 오류는 한국어 ValueError 로 던진다(그래프 진입 노드가 {"error": ...} 로 단락).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field


# ── pydantic 입력 스키마(구조 계약) ───────────────────────────────────────────
class ProjectIn(BaseModel):
    """프로젝트 선택(카드 피커와 동일 단위, code=PJT_NO|WBS_NO)."""

    model_config = ConfigDict(extra="allow")  # wbsNo/wbsNm/loc 등 부가키 보존.

    code: str
    name: str = ""


class GyeongjoIn(BaseModel):
    """`params["gyeongjo"]` — 단건: 증빙일(=회계일) + 정액(총액) + 근속<1년 토글 + 프로젝트.

    거래처·상대계정거래처는 입력받지 않는다(런타임에 작성자 본인 이름으로 검색). 적요도 본인
    이름으로 조립하므로 입력받지 않는다(fill 노드가 '경조금-{본인이름}' 으로 만든다).
    """

    evidenceDate: date  # 증빙일자 = 회계일자(ACTG_DT). 사용자 입력.
    baseAmount: int = Field(gt=0)  # 경조금 정액(총액) — 사용자 입력(규정표 자동 아님).
    under1Year: bool = False  # 근속 1년 미만이면 공급가액 50%(D10-a).
    project: ProjectIn


# ── 공급가액 계산(백엔드 권위, D10-a) ─────────────────────────────────────────
def supply_amount(base_amount: int, under1_year: bool) -> int:
    """공급가액 = 근속 1년 미만이면 정액 × 0.5(원 단위 ROUND_HALF_UP), 아니면 정액 그대로.

    사용자 확정(2026-07-13): 정액은 사용자 입력 총액. 원 단위 반올림은 국내출장 유류비
    (fuel_support_amount)와 동일하게 Decimal + ROUND_HALF_UP(사사오입)로 한다 — 파이썬 내장
    round() 는 은행가 반올림(round-half-to-even)이라 .5 경계에서 갈린다(예 100001×0.5=50000.5 →
    round()=50000, 사사오입=50001). Decimal(str(base)) 로 float 오차 없이 정확히 계산한다.
    """
    if under1_year:
        half = Decimal(str(base_amount)) * Decimal("0.5")
        return int(half.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return base_amount


# ── 정규화(그래프 진입 노드가 소비할 plan_rows) ──────────────────────────────
def parse_gyeongjo_params(params: dict) -> tuple[list[dict], str]:
    """`params["gyeongjo"]` → (plan_rows[1건], acct_date_compact "YYYYMMDD").

    회계일자 = 증빙일자(사용자 입력) 그대로(단건). 공급가액은 supply_amount 로 확정해 행에 싣는다.
    한국어 ValueError 로 실패. 대표 오류: gyeongjo 누락, 정액 비양수, 프로젝트/증빙일 누락.
    """
    gj = params.get("gyeongjo")
    if not isinstance(gj, dict):
        raise ValueError("경조금 입력(gyeongjo)이 없습니다.")

    # 자주 나오는 케이스는 한국어 메시지로 선검사한다(pydantic 원문보다 친절).
    base = gj.get("baseAmount")
    if not isinstance(base, int) or isinstance(base, bool) or base <= 0:
        raise ValueError("경조금 정액(baseAmount)은 0보다 큰 정수여야 합니다.")
    if not str((gj.get("project") or {}).get("code") or "").strip():
        raise ValueError("프로젝트가 없습니다.")
    if not str(gj.get("evidenceDate") or "").strip():
        raise ValueError("증빙일자(evidenceDate)가 없습니다.")

    try:
        parsed = GyeongjoIn.model_validate(gj)
    except ValueError as exc:  # pydantic ValidationError 는 ValueError 서브클래스.
        raise ValueError(f"경조금 입력 형식이 올바르지 않습니다: {exc}") from exc

    amount = supply_amount(parsed.baseAmount, parsed.under1Year)
    project = {
        "code": parsed.project.code,
        "name": parsed.project.name,
        **(parsed.project.model_extra or {}),
    }
    compact = parsed.evidenceDate.strftime("%Y%m%d")  # START_DT(계산서일)·ACTG_DT 세팅용.
    plan_rows = [
        {
            "invoiceDate": compact,
            "amount": amount,  # 확정 공급가액(근속<1년이면 반값).
            "project": project,
            "baseAmount": parsed.baseAmount,  # 요약용(정액 원본).
            "under1Year": parsed.under1Year,
        }
    ]
    # 회계일자(ACTG_DT) = 증빙일자 그대로(단건, 사용자 입력).
    return plan_rows, compact
