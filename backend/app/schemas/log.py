"""접속 로그 응답 스키마 — "로깅" 화면 소스."""

from __future__ import annotations

from datetime import datetime

from app.schemas.common import CamelModel, ListPage


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


class AccessLogPage(ListPage[AccessLogOut]):
    """dual-key envelope — 표준 키(items/total/limit/offset)는 ListPage 상속, 구 키(logs)에
    같은 목록을 병기한다. FE 전환 배포 확인 후 별도 커밋에서 logs 키 제거 예정
    (docs/LIST-COMMONALIZATION.md).
    """

    logs: list[AccessLogOut]
