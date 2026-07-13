"""CardLearnedNote ORM 모델 — 사용자 개입 학습((가맹점 × 계정) → 적요) 저장.

card-collect 그리드 개입에서 사람이 **예산단위(=계정)를 바꾸고 적요를 확정**하면, 그 계정에 맞는
적요를 (user_id, norm_merchant, acct_code) 단위로 누적한다. 다음 런에서 같은 가맹점의 같은 계정이
나오면 그 계정 전용 적요를 결정적으로 추천한다.

⚠ 기존 `card_learned_selections`(가맹점 → 예산단위 선택)와 **병행 유지** — 이 테이블은 계정별
적요만 담당한다. 같은 (가맹점 × 계정)을 여러 번 확정해도 유니크로 1행에 접히고(count++) 최신
적요로 갱신한다. users 삭제 시 CASCADE.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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

from app.models.base import Base


class CardLearnedNote(Base):
    __tablename__ = "card_learned_notes"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "norm_merchant", "acct_code", name="uq_card_learned_note_user_merchant_acct"
        ),
        Index("ix_card_learned_note_user", "user_id"),
        Index("ix_card_learned_note_merchant", "norm_merchant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 정규화 가맹점명(매칭 키) + 원문(표시·디버깅용).
    norm_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    # 사람이 고른 계정(예산계정) — 조합 키의 일부라 non-null(코드 없으면 쓰기경로에서 skip).
    acct_code: Mapped[str] = mapped_column(String(32), nullable=False)
    acct_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 이 (가맹점 × 계정)에 대해 사람이 확정한 최신 적요.
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 같은 조합 재확정 횟수(가중치·결정적 적용 판정에 사용).
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<CardLearnedNote user={self.user_id} merchant={self.merchant!r} "
            f"acct={self.acct_code!r} note={self.note!r} n={self.count}>"
        )
