"""비용구분(소속 팀 cost_type) → 기본 프로젝트 해석 — card·trip 공용 단일 소스.

조직 설정(소속 팀 비용구분)과 프로젝트 기본값을 일치시킨다: **제조원가→PJT_NO 500 / 판관비→800**
(ERP 에 비용구분 동명 프로젝트 존재, 카탈로그 실측 2026-07-04). 카드는 collect 노드가, 출장은
실행 전 폼(`GET /me/trip-defaults`)이 같은 규칙으로 기본 프로젝트를 프리셀렉트한다.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import ErpCodeCatalog

# 비용구분 → 기본 프로젝트 PJT_NO.
COST_PROJECT_NO: dict[str, str] = {"제조원가": "500", "판관비": "800"}


async def resolve_cost_project(cost_type: str | None) -> dict | None:
    """비용구분 기본 프로젝트({code,name,wbsNo,wbsNm}) — 카탈로그(kind='project')에서 조회.

    제조원가→PJT_NO 500, 판관비→800. 알 수 없는 구분·카탈로그 미존재면 None(호출부가 폴백).
    WBS 행이 여럿이면 wbsNo 오름차순 첫 행(500|500 처럼 프로젝트 번호와 동일 WBS 우선).
    """
    pjt_no = COST_PROJECT_NO.get((cost_type or "").strip())
    if not pjt_no:
        return None
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(
                select(ErpCodeCatalog).where(
                    ErpCodeCatalog.kind == "project",
                    ErpCodeCatalog.code.like(f"{pjt_no}|%"),
                )
            )
        ).scalars().all()
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: ((r.extra or {}).get("wbsNo") or ""))
    exact = next((r for r in rows if ((r.extra or {}).get("wbsNo") or "") == pjt_no), rows[0])
    extra = exact.extra or {}
    return {
        "code": exact.code,
        "name": exact.name,
        "wbsNo": extra.get("wbsNo", ""),
        "wbsNm": extra.get("wbsNm", ""),
    }
