"""Role ORM 모델 — 단일 테넌트 전역 롤(super_admin/admin/user)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.role_permission import RolePermission
    from app.models.user import User


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    users: Mapped[list[User]] = relationship(back_populates="role")

    def __repr__(self) -> str:
        return f"<Role code={self.code}>"
