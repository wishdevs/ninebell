"""Permission ORM 모델 (문자열 코드 기반)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.role_permission import RolePermission


class Permission(Base):
    """``users:read`` 같은 명명 권한."""

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="permission",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Permission code={self.code}>"
