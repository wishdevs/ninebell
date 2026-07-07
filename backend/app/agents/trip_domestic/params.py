"""출장(국내/자차) 실행 전 폼 파라미터 — pydantic 스키마 + 유류비 계산 + 정규화.

실행 방식이 card 와 다르다: card 는 HITL 로 사람이 화면에서 값을 고르지만, 출장은
**모든 입력이 사용자 제공**이라 실행 전 폼으로 받은 `body.params["trip"]` 을 그래프
진입 노드(validate_params)가 검증·정규화해 `plan_rows` 로 만든다. 브라우저 불필요.

- 유류비 금액은 **백엔드 권위**다: `fuel_support_amount` 가 Decimal + ROUND_HALF_UP 로
  계산한다. 파이썬 내장 `round()` 는 은행가 반올림(round-half-to-even)이라 금지.
  클라이언트가 fuel 행에 amount 를 실어 보내도 **무시하고 재계산**한다.
- 모든 검증 오류는 한국어 ValueError 로 던진다(그래프 진입 노드가 {"error": ...} 로 단락).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any, Literal, Mapping, Union

from pydantic import BaseModel, ConfigDict, Field

# 차량종류 → 기준연비 설정 키. agent_settings.py AGENT_SETTINGS_SCHEMA["trip-domestic"] 와 정합.
CAR_CLASS_EFF_KEY: dict[str, str] = {
    "under1000": "fuel_eff_under_1000",
    "under1600": "fuel_eff_under_1600",
    "under2000": "fuel_eff_under_2000",
    "over2000": "fuel_eff_over_2000",
}
FUEL_UNIT_PRICE_KEY = "fuel_unit_price"

CarClass = Literal["under1000", "under1600", "under2000", "over2000"]

DEFAULT_TOLL_NOTE = "통행료(현금)"
DEFAULT_FUEL_NOTE = "국내출장 자차 유류비 지원"


# ── pydantic 입력 스키마(구조 계약) ───────────────────────────────────────────
class ProjectIn(BaseModel):
    """행별 프로젝트 선택(카드 피커와 동일 단위, code=PJT_NO|WBS_NO)."""

    model_config = ConfigDict(extra="allow")  # wbsNo/wbsNm/loc 등 부가키 보존.

    code: str
    name: str = ""


class TollRowIn(BaseModel):
    """통행료 행 — 거래처(공공기관) + 공급가액(입력 금액)."""

    type: Literal["toll"] = "toll"
    partnerCode: str
    partnerName: str
    amount: int = Field(gt=0)
    project: ProjectIn
    note: str = DEFAULT_TOLL_NOTE


class FuelRowIn(BaseModel):
    """유류비 지원 행 — km + 차량종류. amount 는 받지 않고 백엔드가 계산한다."""

    type: Literal["fuel"] = "fuel"
    km: int = Field(gt=0)
    carClass: CarClass
    project: ProjectIn
    note: str = DEFAULT_FUEL_NOTE


RowIn = Annotated[Union[TollRowIn, FuelRowIn], Field(discriminator="type")]


class TripParams(BaseModel):
    """`params["trip"]` 전체 — 회계일자(문서당 1개) + 행 목록(1..20)."""

    acctDate: date
    rows: list[RowIn] = Field(min_length=1, max_length=20)


# ── 유류비 계산(백엔드 권위) ──────────────────────────────────────────────────
def fuel_support_amount(km: int, car_class: str, settings: Mapping[str, Any]) -> int:
    """km ÷ 차량별 기준연비 × 기준단가 → 원 단위 ROUND_HALF_UP.

    설정(연비/단가)은 effective_settings 로 병합된 실효값을 넘긴다. 연비/단가가 ≤0 이면
    ValueError(한국어). 내장 round() 금지 — Decimal.quantize(ROUND_HALF_UP) 로 고정.
    """
    eff_key = CAR_CLASS_EFF_KEY.get(car_class)
    if eff_key is None:
        raise ValueError(f"알 수 없는 차량종류입니다: {car_class}")
    try:
        eff = Decimal(str(settings.get(eff_key)))
        unit_price = Decimal(str(settings.get(FUEL_UNIT_PRICE_KEY)))
    except (InvalidOperation, TypeError):
        raise ValueError("유류비 설정값(연비·단가)이 올바르지 않습니다.")
    if eff <= 0:
        raise ValueError("기준연비는 0보다 커야 합니다.")
    if unit_price <= 0:
        raise ValueError("기준단가는 0보다 커야 합니다.")
    # 곱셈 먼저(km×단가) 후 나눗셈 — 나눗셈을 먼저 하면 비종결 몫(예: 11/6)이 컨텍스트
    # 정밀도로 반올림돼 정확한 .5 경계에서 1원 낮게 나온다(리뷰: 11·153·6 → 280.5).
    amount = (Decimal(km) * unit_price) / eff
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ── 정규화(그래프 진입 노드가 소비할 plan_rows) ──────────────────────────────
def _normalize_row(row: Union[TollRowIn, FuelRowIn], settings: Mapping[str, Any]) -> dict:
    """검증된 행 → plan_row dict(모든 행이 동일 키 셋; 미해당 필드는 None/"" ).

    fuel 행: partnerCode/partnerName 은 런타임 본인이름 검색이라 비운다("").
             amount 는 fuel_support_amount 로 계산해 채운다.
    """
    project = {"code": row.project.code, "name": row.project.name, **(row.project.model_extra or {})}
    if isinstance(row, TollRowIn):
        return {
            "type": "toll",
            "partnerCode": row.partnerCode,
            "partnerName": row.partnerName,
            "amount": row.amount,
            "project": project,
            "note": row.note,
            "km": None,
            "carClass": None,
        }
    return {
        "type": "fuel",
        "partnerCode": "",
        "partnerName": "",
        "amount": fuel_support_amount(row.km, row.carClass, settings),
        "project": project,
        "note": row.note,
        "km": row.km,
        "carClass": row.carClass,
    }


def parse_trip_params(params: dict, settings: Mapping[str, Any]) -> tuple[list[dict], str]:
    """`params["trip"]` → (plan_rows, acct_date_compact "YYYYMMDD").

    한국어 ValueError 로 실패. 대표 오류: 회계일자 누락, rows 빈 배열, 통행료 거래처 누락,
    잘못된 차량종류, km/금액 비양수. settings 는 effective_settings 실효값(연비·단가).
    """
    trip = params.get("trip")
    if not isinstance(trip, dict):
        raise ValueError("출장 입력(trip)이 없습니다.")

    if not trip.get("acctDate"):
        raise ValueError("회계일자가 없습니다.")

    raw_rows = trip.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) == 0:
        raise ValueError("입력 행이 없습니다. 최소 1건을 추가하세요.")

    # 구조/타입 검증은 pydantic 에 맡기되, 자주 나오는 케이스는 한국어 메시지로 선검사한다.
    for i, r in enumerate(raw_rows):
        if not isinstance(r, dict):
            raise ValueError(f"{i + 1}번째 행 형식이 올바르지 않습니다.")
        rtype = r.get("type")
        if rtype == "toll":
            if not str(r.get("partnerCode") or "").strip() or not str(r.get("partnerName") or "").strip():
                raise ValueError("통행료 행에 거래처가 없습니다.")
            amount = r.get("amount")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                raise ValueError("통행료 금액은 0보다 큰 정수여야 합니다.")
        elif rtype == "fuel":
            if r.get("carClass") not in CAR_CLASS_EFF_KEY:
                raise ValueError(f"알 수 없는 차량종류입니다: {r.get('carClass')}")
            km = r.get("km")
            if not isinstance(km, int) or isinstance(km, bool) or km <= 0:
                raise ValueError("주행거리(km)는 0보다 큰 정수여야 합니다.")
        else:
            raise ValueError(f"알 수 없는 행 유형입니다: {rtype}")
        if not str((r.get("project") or {}).get("code") or "").strip():
            raise ValueError(f"{i + 1}번째 행에 프로젝트가 없습니다.")

    try:
        parsed = TripParams.model_validate(trip)
    except ValueError as exc:  # pydantic ValidationError 는 ValueError 서브클래스.
        raise ValueError(f"출장 입력 형식이 올바르지 않습니다: {exc}") from exc

    plan_rows = [_normalize_row(row, settings) for row in parsed.rows]
    acct_date_compact = parsed.acctDate.strftime("%Y%m%d")
    return plan_rows, acct_date_compact
