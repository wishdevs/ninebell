"""구매발주 계획서 라우터 — 확정 계획서 조회.

- GET /purchase-order/plans      : 목록(최신순 페이지). 본인 것만, logs:read(관리자)는 전체.
- GET /purchase-order/plans/{id} : 단건(plan·bomSummary 포함). 타인 것은 404(존재 숨김).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, user_has_permission
from app.core.listing import PageQuery, paginate
from app.core.permissions import LOGS_READ
from app.models import PurchaseOrderPlan
from app.services import purchase_order_resume

router = APIRouter(prefix="/purchase-order/plans", tags=["purchase-order"])


def _plan_summary(p: PurchaseOrderPlan) -> dict:
    u = p.user
    return {
        "id": str(p.id),
        "runId": p.run_id,
        "agentId": p.agent_id,
        "project": {"code": p.project_code, "name": p.project_name},
        "wbs": p.wbs,
        "unitCount": p.unit_count,
        "totalAmount": p.total_amount,
        "userId": str(p.user_id),
        "userDisplayName": (u.display_name or u.omnisol_userid) if u is not None else None,
        "createdAt": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("")
async def list_plans(
    user: CurrentUser, db: DbSession, page: PageQuery, q: str | None = None
) -> dict:
    stmt = select(PurchaseOrderPlan).order_by(PurchaseOrderPlan.created_at.desc())
    # 관리자(logs:read)는 전체, 일반 사용자는 소유 스코프 — runs 목록과 같은 규칙.
    if not user_has_permission(user, LOGS_READ):
        stmt = stmt.where(PurchaseOrderPlan.user_id == user.id)
    # 검색(2026-08-31) — 프로젝트명·코드·WBS 부분일치(대소문자 무시).
    term = (q or "").strip()[:80]
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            PurchaseOrderPlan.project_name.ilike(like)
            | PurchaseOrderPlan.project_code.ilike(like)
            | PurchaseOrderPlan.wbs.ilike(like)
        )
    result = await paginate(db, stmt, page)
    return {
        "items": [_plan_summary(p) for p in result.items],
        "total": result.total,
        "limit": result.limit,
        "offset": result.offset,
    }


@router.get("/{plan_id}")
async def get_plan(plan_id: str, user: CurrentUser, db: DbSession) -> dict:
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="계획서를 찾을 수 없습니다."
    )
    try:
        parsed = uuid.UUID(plan_id)
    except ValueError:
        raise not_found
    stmt = select(PurchaseOrderPlan).where(PurchaseOrderPlan.id == parsed)
    if not user_has_permission(user, LOGS_READ):
        stmt = stmt.where(PurchaseOrderPlan.user_id == user.id)
    p = (await db.execute(stmt)).scalar_one_or_none()
    if p is None:
        raise not_found
    return {**_plan_summary(p), "plan": p.plan, "bomSummary": p.bom_summary}


# ── 자동 재개 후보(2026-08-31) — 구매발주 페이지 '이어서 실행' 배너용 ────────────
# /purchase-order/plans/{plan_id} 와 경로가 겹치지 않게 별도 라우터(prefix /purchase-order).
resume_router = APIRouter(prefix="/purchase-order", tags=["purchase-order"])


@resume_router.get("/resume-candidates")
async def list_resume_candidates(user: CurrentUser) -> list[dict]:
    """중단된 프로젝트 목록 — 저장된 구매요청 중 상신·발주가 끝나지 않은 건이 남은 프로젝트.

    소유 스코프(본인 런) 기준 — 재개 주체는 실행자 본인이다. logs:read(관리자)는 전체.
    """
    scope_user = None if user_has_permission(user, LOGS_READ) else user.id
    return await purchase_order_resume.resume_candidates(user_id=scope_user)
