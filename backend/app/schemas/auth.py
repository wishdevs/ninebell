"""인증 관련 요청/응답 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import CamelModel


class LoginBody(BaseModel):
    userid: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class AuthMe(CamelModel):
    """GET /auth/me — 현재 사용자 + 평탄화된 권한."""

    id: str
    omnisol_userid: str
    display_name: str | None
    department: str | None
    email: str | None
    role: str
    permissions: list[str]
    last_login_at: datetime | None
