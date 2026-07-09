"""출장(해외/정산서) 실행 전 폼 파라미터 — pydantic 스키마 + 정규화.

국내/자차와 기본틀은 같으나 **유형(통행료/유류비) 구분이 없다**. 모든 행이 동일 형태:
(세금)계산서일(증빙일) + 공급가액(총 금액) + 프로젝트 + 적요(자유 입력). 거래처·상대계정거래처는
작성자 본인(런타임 검색). 회계일자는 계산서일(증빙일) 최댓값(가장 마지막일)으로 파생(사용자 결정).

- 금액 계산 없음(국내 자차의 유류비 fuel_support_amount 미사용) — 공급가액은 사용자가 입력한 총액.
- 모든 검증 오류는 한국어 ValueError 로 던진다(그래프 진입 노드가 {"error": ...} 로 단락).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


# ── pydantic 입력 스키마(구조 계약) ───────────────────────────────────────────
class ProjectIn(BaseModel):
    """행별 프로젝트 선택(카드 피커와 동일 단위, code=PJT_NO|WBS_NO)."""

    model_config = ConfigDict(extra="allow")  # wbsNo/wbsNm/loc 등 부가키 보존.

    code: str
    name: str = ""


class RowIn(BaseModel):
    """해외 정산서 행 — 계산서일(증빙일) + 공급가액(총금액) + 프로젝트 + 적요(자유 입력).

    거래처·상대계정거래처는 입력받지 않는다(런타임에 작성자 본인 이름으로 검색). 유형 구분 없음.
    """

    invoiceDate: date  # (세금)계산서일 = 증빙일. 행별 입력.
    amount: int = Field(gt=0)  # 공급가액 = 총 금액(입력).
    project: ProjectIn
    note: str = Field(min_length=1)  # 적요(자유 입력, 예: 해외출장 일비 / 해외출장 경비).


class TripParams(BaseModel):
    """`params["trip"]` 전체 — 행 목록(1..20). 회계일자는 계산서일 최댓값으로 파생(입력 없음)."""

    rows: list[RowIn] = Field(min_length=1, max_length=20)


# ── 정규화(그래프 진입 노드가 소비할 plan_rows) ──────────────────────────────
def _normalize_row(row: RowIn) -> dict:
    """검증된 행 → plan_row dict(모든 행 동일 키 셋). invoiceDate 는 START_DT 세팅용 compact."""
    project = {"code": row.project.code, "name": row.project.name, **(row.project.model_extra or {})}
    return {
        "invoiceDate": row.invoiceDate.strftime("%Y%m%d"),
        "amount": row.amount,
        "project": project,
        "note": row.note,
    }


def parse_trip_params(params: dict, settings: Mapping[str, Any]) -> tuple[list[dict], str]:
    """`params["trip"]` → (plan_rows, acct_date_compact "YYYYMMDD").

    회계일자는 입력받지 않고 **계산서일(증빙일) 중 가장 마지막일**로 파생한다(사용자 결정).
    settings 는 국내 자차와 시그니처를 맞추기 위해 받되 사용하지 않는다(해외는 금액 계산 없음).
    한국어 ValueError 로 실패. 대표 오류: rows 빈 배열, 공급가액 비양수, 프로젝트/계산서일/적요 누락.
    """
    trip = params.get("trip")
    if not isinstance(trip, dict):
        raise ValueError("출장 입력(trip)이 없습니다.")

    raw_rows = trip.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) == 0:
        raise ValueError("입력 행이 없습니다. 최소 1건을 추가하세요.")

    # 구조/타입 검증은 pydantic 에 맡기되, 자주 나오는 케이스는 한국어 메시지로 선검사한다.
    for i, r in enumerate(raw_rows):
        if not isinstance(r, dict):
            raise ValueError(f"{i + 1}번째 행 형식이 올바르지 않습니다.")
        amount = r.get("amount")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError(f"{i + 1}번째 행 공급가액은 0보다 큰 정수여야 합니다.")
        if not str((r.get("project") or {}).get("code") or "").strip():
            raise ValueError(f"{i + 1}번째 행에 프로젝트가 없습니다.")
        if not str(r.get("invoiceDate") or "").strip():
            raise ValueError(f"{i + 1}번째 행에 계산서일(증빙일)이 없습니다.")
        if not str(r.get("note") or "").strip():
            raise ValueError(f"{i + 1}번째 행에 적요가 없습니다.")

    try:
        parsed = TripParams.model_validate(trip)
    except ValueError as exc:  # pydantic ValidationError 는 ValueError 서브클래스.
        raise ValueError(f"출장 입력 형식이 올바르지 않습니다: {exc}") from exc

    plan_rows = [_normalize_row(row) for row in parsed.rows]
    # 회계일자 = 계산서일(증빙일) 최댓값(가장 마지막일). 사용자 입력 없이 파생.
    acct_date_compact = max(row.invoiceDate for row in parsed.rows).strftime("%Y%m%d")
    return plan_rows, acct_date_compact
