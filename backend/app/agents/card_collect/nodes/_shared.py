"""카드수집 노드 공용 헬퍼 — 포맷·추천적요·처리현황표·행 키·프레임 상수."""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

# 그리드 프레임 크기 가드(프론트 페이로드 비대 방지).
_MAX_BUDGET_UNITS = 200
_MAX_PROJECT_RESULTS = 25
_MAX_FAVORITES = 100

# 코드피커 필드 스펙: 폼 id → (팝업 code 컬럼, name 컬럼). probe5~8 실측.
# 채움 순서는 예산단위 → 프로젝트. 계정(acct_cd)은 예산단위 선택으로 **자동 결정**되므로
# 피커를 열지 않는다(사용자 확정 2026-07-04 — 기존 자동축소 선택 제거).
FIELD_SPEC: dict[str, dict[str, str]] = {
    "예산단위": {"id": "bg_cd", "code": "BG_CD", "name": "BG_NM"},
    "프로젝트": {"id": "pjt_cd", "code": "PJT_NO", "name": "PJT_NM"},
}


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _fmt_won(v: Any) -> str:
    if v is None or str(v).strip() == "":
        return "-"  # 그리드에 값이 없는 컬럼(예: 부가세 미제공 행)은 'None원' 대신 '-'.
    try:
        return f"{int(str(v).replace(',', '')):,}원"
    except (ValueError, TypeError):
        return f"{v}원"


def recommend_note(tran_nm: str, amount: str) -> str:
    """가맹점명 기반 적요 초안 추천(휴리스틱 v1, 추후 Gemini 로 고도화).

    ⚠ 법인 접미(주식회사·(주)·㈜)를 매칭 전에 제거한다 — 안 그러면 '식'(식대 키워드)이
    '주**식**회사'에 걸려 모든 법인 가맹점이 '식대'로 오분류되고(2026-07-24 동구전자 실측),
    그 draft 적요가 AI 계정 판단까지 복리후생비로 오도한다. 음식 키워드도 단문자 '식' 대신
    '식당·식품·음식' 등 구체어를 쓴다.
    """
    nm = tran_nm or ""
    nm_match = re.sub(r"주식회사|유한회사|㈜|\(주\)|（주）", " ", nm)  # 법인 접미 제거 후 매칭.
    rules = [
        (("식당", "식품", "음식", "분식", "한식", "중식당", "일식", "푸드", "요기요", "배달",
          "김밥", "곱창", "고기", "치킨", "피자", "카페", "커피"), "식대(법인카드)"),
        (("주차", "파킹"), "주차료(법인카드)"),
        (("택시", "카카오T", "코레일", "고속", "항공", "대한항공", "아시아나"), "교통비(법인카드)"),
        (("주유", "에너지", "오일", "GS칼텍스", "SK에너지"), "차량 주유비(법인카드)"),
        (("네이버", "쿠팡", "11번가", "G마켓", "다이소", "코스트코", "이마트"), "소모품 구입(법인카드)"),
    ]
    for keys, note in rules:
        if any(k in nm_match for k in keys):
            return note
    return f"{nm} 사용" if nm else "법인카드 사용"


def _params_today(state: dict) -> date:
    """params['today'] 재정의(테스트/재현용) 지원 — set_period 와 동일 규약."""
    params = state.get("params") or {}
    raw = params.get("today")
    if raw:
        try:
            return date.fromisoformat(str(raw))
        except (ValueError, TypeError):
            pass
    return date.today()


def _params_cutoff_day(state: dict) -> int | None:
    """params['acct_cutoff_day'](회계시점 결정일 — 에이전트 설정에서 주입) 안전 파싱.

    없거나 정수 변환 불가면 None(compute_period 레거시 규칙 폴백).
    """
    params = state.get("params") or {}
    raw = params.get("acct_cutoff_day")
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


# ── 처리 현황 요약 ────────────────────────────────────────────────────────────
_STATUS_ORDER = (
    ("done", "반영"),
    ("wait2", "2차 대기"),
    ("skipped", "건너뜀"),
    ("failed", "실패"),
    ("pending", "대기"),
)


def _row_key(r: dict) -> str:
    """거래 행 식별키 — 승인/취소 쌍이 같은 APRVL_NO 라(프로브 실측) 일자·금액까지 복합."""
    return f"{r.get('APRVL_NO') or ''}|{r.get('TRAN_DT') or ''}|{r.get('TRAN_AMT') or ''}"


def _exclude_reason(r: dict) -> str | None:
    """저장 제외 판정(사용자 규칙 2026-07-29) — 제외면 사유 문자열, 정상이면 None.

    승인번호가 전부 0('00000000')이거나 거래처(가맹점명 TRAN_NM)가 빈 행은 정상 승인
    거래가 아니므로 전표 반영·저장 대상에서 뺀다. 1차 조회와 2차(불공) 재조회 양쪽
    리스트에 적용한다(저장 전 리스트 재확인).
    """
    aprvl = str(r.get("APRVL_NO") or "").strip()
    if aprvl and set(aprvl) == {"0"}:
        return f"승인번호 {aprvl}"
    if not str(r.get("TRAN_NM") or "").strip():
        return "거래처 없음"
    return None


def _status_line(status: dict[int, str]) -> str:
    """처리 현황 한 줄 요약 — 채팅은 화면을 보면서 쓰므로 행별 표 대신 개수만 보여준다
    (사용자 요청 2026-07-29: 채팅이 커서 화면을 가림 + 표가 두 번 반복). 행별 상세는
    그리드·실행 로그가 담당한다."""
    counts: dict[str, int] = {}
    for v in status.values():
        counts[v] = counts.get(v, 0) + 1
    parts = [f"{label} {counts[key]}" for key, label in _STATUS_ORDER if counts.get(key)]
    return " · ".join(parts) + f" (총 {len(status)}행)"
