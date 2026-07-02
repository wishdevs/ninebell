"""접속 로그 응답 스키마 — "로깅" 화면 소스."""

from __future__ import annotations

from datetime import datetime

from app.schemas.common import CamelModel


class AccessLogOut(CamelModel):
    id: str
    user_id: str | None
    omnisol_userid: str
    display_name: str | None
    role: str | None
    status: str
    error_msg: str | None
    ip: str | None
    user_agent: str | None
    logged_at: datetime | None


class AccessLogPage(CamelModel):
    logs: list[AccessLogOut]
    total: int
