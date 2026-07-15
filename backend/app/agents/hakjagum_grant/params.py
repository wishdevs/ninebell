"""학자금신청서 실행 전 폼 파라미터 — pydantic 단건 스키마 + 정규화.

경조금(gyeongjo_grant)과 실행 방식이 같다(모든 입력이 사용자 제공 → 실행 전 폼) — **단건(1행)**:
학자금 1건 = 결의서 1장. 입력은 배열(rows[])이 아니라 단일 객체(`params["hakjagum"]`).

- 공급가액(거래금액)은 **사용자 입력 금액 그대로**다(D10) — 경조금의 근속<1년 50% 규칙이
  **없다**(경조금과 차이, 사용자 확정 2026-07-15). 계산 함수(supply_amount 상당) 자체가 없다.
- 회계일자(ACTG_DT)는 **증빙일자 = 사용자 입력** 그대로다(회계일=계산서일 단일 날짜, D4 —
  단건이라 max 파생 불필요).
- 모든 검증 오류는 한국어 ValueError 로 던진다(그래프 진입 노드가 {"error": ...} 로 단락).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


# ── pydantic 입력 스키마(구조 계약) ───────────────────────────────────────────
class ProjectIn(BaseModel):
    """프로젝트 선택(카드 피커와 동일 단위, code=PJT_NO|WBS_NO)."""

    model_config = ConfigDict(extra="allow")  # wbsNo/wbsNm/loc 등 부가키 보존.

    code: str
    name: str = ""


class HakjagumIn(BaseModel):
    """`params["hakjagum"]` — 단건: 증빙일(=회계일) + 정액(총액) + 프로젝트.

    거래처는 입력받지 않는다(런타임에 작성자 본인 이름으로 검색). 적요도 본인 이름으로 조립하므로
    입력받지 않는다(fill 노드가 '학자금-{본인이름}' 으로 만든다). 근속 토글(under1Year) 없음 —
    공급가액 = 정액 그대로(경조금과 차이).
    """

    evidenceDate: date  # 증빙일자 = 회계일자(ACTG_DT). 사용자 입력.
    baseAmount: int = Field(gt=0)  # 학자금 정액(총액) — 사용자 입력 그대로 공급가액.
    project: ProjectIn


# ── 정규화(그래프 진입 노드가 소비할 plan_rows) ──────────────────────────────
def parse_hakjagum_params(params: dict) -> tuple[list[dict], str]:
    """`params["hakjagum"]` → (plan_rows[1건], acct_date_compact "YYYYMMDD").

    회계일자 = 증빙일자(사용자 입력) 그대로(단건). 공급가액 = baseAmount 그대로 행에 싣는다
    (50% 규칙 없음). 한국어 ValueError 로 실패. 대표 오류: hakjagum 누락, 정액 비양수,
    프로젝트/증빙일 누락.
    """
    hj = params.get("hakjagum")
    if not isinstance(hj, dict):
        raise ValueError("학자금 입력(hakjagum)이 없습니다.")

    # 자주 나오는 케이스는 한국어 메시지로 선검사한다(pydantic 원문보다 친절).
    base = hj.get("baseAmount")
    if not isinstance(base, int) or isinstance(base, bool) or base <= 0:
        raise ValueError("학자금 정액(baseAmount)은 0보다 큰 정수여야 합니다.")
    if not str((hj.get("project") or {}).get("code") or "").strip():
        raise ValueError("프로젝트가 없습니다.")
    if not str(hj.get("evidenceDate") or "").strip():
        raise ValueError("증빙일자(evidenceDate)가 없습니다.")

    try:
        parsed = HakjagumIn.model_validate(hj)
    except ValueError as exc:  # pydantic ValidationError 는 ValueError 서브클래스.
        raise ValueError(f"학자금 입력 형식이 올바르지 않습니다: {exc}") from exc

    project = {
        "code": parsed.project.code,
        "name": parsed.project.name,
        **(parsed.project.model_extra or {}),
    }
    compact = parsed.evidenceDate.strftime("%Y%m%d")  # START_DT(계산서일)·ACTG_DT 세팅용.
    plan_rows = [
        {
            "invoiceDate": compact,
            "amount": parsed.baseAmount,  # 사용자 입력 금액 그대로(50% 규칙 없음).
            "project": project,
        }
    ]
    # 회계일자(ACTG_DT) = 증빙일자 그대로(단건, 사용자 입력).
    return plan_rows, compact
