"""AccessLog ORM 모델 — 로그인 시도(성공/실패) 기록. "로깅" 화면의 소스."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AccessLog(Base):
    __tablename__ = "access_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 실패(미등록 계정 등) 시 user_id 는 null.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    omnisol_userid: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # success | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AccessLog userid={self.omnisol_userid} status={self.status}>"
