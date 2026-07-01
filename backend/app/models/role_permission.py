"""roles ↔ permissions 연결 테이블.

super_admin·admin 이 동일 권한을 갖더라도 **각각 별도 행** 으로 저장된다.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.permission import Permission
    from app.models.role import Role


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role: Mapped[Role] = relationship(back_populates="role_permissions")
    permission: Mapped[Permission] = relationship(
        back_populates="role_permissions",
        lazy="selectin",
    )
