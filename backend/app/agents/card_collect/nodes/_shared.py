"""카드수집 노드 공용 헬퍼 — 포맷·추천적요·처리현황표·행 키·프레임 상수."""

from __future__ import annotations

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
    """가맹점명 기반 적요 초안 추천(휴리스틱 v1, 추후 Gemini 로 고도화)."""
    nm = tran_nm or ""
    rules = [
        (("식", "푸드", "요기요", "배달", "김밥", "곱창", "고기"), "식대(법인카드)"),
        (("주차", "파킹"), "주차료(법인카드)"),
        (("택시", "카카오T", "코레일", "고속", "항공", "대한항공", "아시아나"), "교통비(법인카드)"),
        (("주유", "에너지", "오일", "GS칼텍스", "SK에너지"), "차량 주유비(법인카드)"),
        (("네이버", "쿠팡", "11번가", "G마켓", "다이소", "코스트코", "이마트"), "소모품 구입(법인카드)"),
    ]
    for keys, note in rules:
        if any(k in nm for k in keys):
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


# ── 리스트 표 / 항목 지정 파서 ─────────────────────────────────────────────────
def _md_cell(v: object) -> str:
    """마크다운 표 셀 안전화(파이프·개행 제거)."""
    return str(v or "").replace("|", "/").replace("\n", " ").strip()


_STATUS_MARK = {
    "done": "✅ 반영",
    "skipped": "⏭️ 건너뜀",
    "failed": "❌ 실패",
    "pending": "· 대기",
    "wait2": "🕓 2차(불공) 대기",
}


def _row_key(r: dict) -> str:
    """거래 행 식별키 — 승인/취소 쌍이 같은 APRVL_NO 라(프로브 실측) 일자·금액까지 복합."""
    return f"{r.get('APRVL_NO') or ''}|{r.get('TRAN_DT') or ''}|{r.get('TRAN_AMT') or ''}"


def _status_table(rows: list[dict], status: dict[int, str], notes: dict[int, str]) -> str:
    """처리 현황 마크다운 표(# · 가맹점명 · 승인액 · 적요 · 상태)."""
    head = "| # | 가맹점명 | 승인액 | 적요 | 상태 |\n|---:|---|---:|---|---|"
    lines = [head]
    for r in rows:
        i = r.get("i", 0)
        lines.append(
            f"| {i + 1} | {_md_cell(r.get('TRAN_NM'))} | {_md_cell(_fmt_won(r.get('TRAN_AMT')))} "
            f"| {_md_cell(notes.get(i, ''))} | {_STATUS_MARK.get(status.get(i, 'pending'))} |"
        )
    return "\n".join(lines)
