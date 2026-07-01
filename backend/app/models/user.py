"""User ORM 모델 — 더존 옴니솔 계정 매핑(로컬 비밀번호 저장 없음)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.role import Role


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 로그인 식별자(더존 userid). 옴니솔 계정은 비밀번호를 절대 저장하지 않는다.
    omnisol_userid: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    # 로컬 계정 전용 bcrypt 해시(예: 시스템 관리자 admin). 옴니솔 계정은 null.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # 회원가입 약관 동의 시각(가입한 옴니솔 계정). 미동의/미가입은 null.
    agreed_terms_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # active | suspended
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped[Role | None] = relationship(back_populates="users", lazy="selectin")

    def __repr__(self) -> str:
        return f"<User omnisol_userid={self.omnisol_userid}>"
