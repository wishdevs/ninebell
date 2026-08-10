"""조직 조회 공용 헬퍼 — user 소속 팀(OrgUnit)의 비용구분(판관비/제조원가).

me_codes(note-suggest·trip-defaults)와 runs(collect params 주입)에 3중복이던 조회를 단일화.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrgUnit, User


async def user_cost_type(db: AsyncSession, user: User) -> str | None:
    """user 소속 조직구분(팀)의 cost_type. 소속 미지정·팀 미존재·구분 없음이면 None."""
    if not user.org_unit_id:
        return None
    team = await db.get(OrgUnit, user.org_unit_id)
    return team.cost_type if team is not None else None
