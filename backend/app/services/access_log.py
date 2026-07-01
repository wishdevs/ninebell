"""접속 로그 기록 헬퍼 — 로그인 시도(성공/실패)를 access_logs 에 적재."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccessLog


async def record_access(
    db: AsyncSession,
    *,
    omnisol_userid: str,
    status: str,
    user_id: uuid.UUID | None = None,
    error_msg: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AccessLog:
    """access_logs 행을 추가(flush)하고 반환. commit 은 호출자가 한다."""
    entry = AccessLog(
        user_id=user_id,
        omnisol_userid=omnisol_userid,
        status=status,
        error_msg=error_msg,
        ip=ip,
        user_agent=user_agent,
    )
    db.add(entry)
    await db.flush()
    return entry
