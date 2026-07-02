"""UserCodeFavorite ORM 모델 — 사용자별 즐겨찾는 ERP 코드(예산단위/프로젝트).

카드결의 등에서 자주 쓰는 예산단위·프로젝트 코드를 사용자가 즐겨찾기로 고정해 둔다.
kind='budget_unit'|'project'. 소유자(user_id)만 조회·추가·삭제·순서변경할 수 있다.
name/extra 는 코드 카탈로그에서 복사해 온 스냅샷(카탈로그가 갱신돼도 즐겨찾기는 유지).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONVariant


class UserCodeFavorite(Base):
    __tablename__ = "user_code_favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "code", name="uq_user_code_favorites_user_id"),
        Index("ix_user_code_favorites_user_id_kind", "user_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 'budget_unit'(예산단위) | 'project'(프로젝트).
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 부가 스냅샷(예: {"deptNm": ...}) — 카탈로그에서 복사.
    extra: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # (user, kind) 당 1개만 True — 단일성은 라우터(POST /me/favorites/{id}/default)가 보장.
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<UserCodeFavorite user={self.user_id} kind={self.kind} code={self.code}>"
