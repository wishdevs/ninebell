"""사용자(멤버) 관련 요청/응답 스키마 — 프론트 WorkspaceMember 형태."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import CamelModel

RoleCode = Literal["super_admin", "admin", "user"]
MemberStatus = Literal["active", "suspended"]


class UserOut(CamelModel):
    """GET /users 항목 — 프론트 WorkspaceMember."""

    id: str
    name: str
    email: str
    role: str
    status: str
    email_verified: bool
    last_active_at: datetime | None
    joined_at: datetime | None
    org_unit_id: str | None = None  # 소속 조직구분(실행 조직접근 게이트 기준)


class RoleUpdate(BaseModel):
    role: RoleCode


class UserPatch(CamelModel):
    status: MemberStatus | None = None
    # 소속 조직구분 지정/해제. 미포함=변경 없음, null/""=해제(model_fields_set 로 구분).
    org_unit_id: str | None = None
