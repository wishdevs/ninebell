"""접속 로그 라우터 — GET /logs. logs:read 게이트(admin+). 최신순 + 페이지네이션."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import DbSession, require_permission
from app.core.permissions import LOGS_READ
from app.models import AccessLog, User
from app.schemas.log import AccessLogOut, AccessLogPage

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=AccessLogPage)
async def list_access_logs(
    db: DbSession,
    _actor: Annotated[User, Depends(require_permission(LOGS_READ))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> AccessLogPage:
    # 서버사이드 검색은 omnisol_userid 대상. displayName 은 아래에서 별도 조회하는 User
    # 조인 결과라 여기서는 필터링할 수 없다.
    conditions = []
    if q is not None and q.strip():
        conditions.append(AccessLog.omnisol_userid.ilike(f"%{q.strip()}%"))
    if status in ("success", "failed"):
        conditions.append(AccessLog.status == status)

    count_stmt = select(func.count()).select_from(AccessLog)
    rows_stmt = select(AccessLog).order_by(AccessLog.logged_at.desc()).limit(limit).offset(offset)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        rows_stmt = rows_stmt.where(condition)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(rows_stmt)).scalars().all()

    # displayName / role 을 위해 관련 사용자 일괄 조회.
    user_ids = {r.user_id for r in rows if r.user_id is not None}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        found = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        users = {u.id: u for u in found}

    out: list[AccessLogOut] = []
    for r in rows:
        u = users.get(r.user_id) if r.user_id is not None else None
        out.append(
            AccessLogOut(
                id=str(r.id),
                user_id=str(r.user_id) if r.user_id is not None else None,
                omnisol_userid=r.omnisol_userid,
                display_name=(u.display_name or u.omnisol_userid) if u is not None else None,
                role=(u.role.code if u is not None and u.role is not None else None),
                status=r.status,
                error_msg=r.error_msg,
                ip=r.ip,
                user_agent=r.user_agent,
                logged_at=r.logged_at,
            )
        )
    return AccessLogPage(logs=out, total=total)
