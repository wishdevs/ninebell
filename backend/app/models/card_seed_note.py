"""CardSeedNote ORM 모델 — 전사 기초자료((가맹점 × 계정) → 적요) 집계 저장.

`card_seed_selections`(가맹점 → 예산단위)와 **별개**로, 같은 가맹점이라도 **계정(예산단위)마다
다른 적요**를 결정적으로 추천하기 위한 전용 tier. 카드 개입에서 사람이 예산단위(=계정)를 바꾸면
그 계정에 맞는 최빈 적요를 골라준다. 개인 학습(card_learned_notes)이 없을 때의 전사 폴백.

⚠ 트랜잭션이 아니라 **(가맹점 × 계정)** 조합 단위 1행 — 유니크 `(norm_merchant, acct_code)`.
매칭 키(norm_merchant)는 개인 학습/seed 와 동일한 정규화를 쓴다. dominance = 그 조합 안에서
최근성 가중 최빈 적요의 비율(신뢰도), last_year = 최근 관측 연도.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CardSeedNote(Base):
    __tablename__ = "card_seed_notes"
    __table_args__ = (
        UniqueConstraint("norm_merchant", "acct_code", name="uq_card_seed_note_merchant_acct"),
        Index("ix_card_seed_note_merchant", "norm_merchant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 정규화 가맹점명(매칭 키, 지점 단위 유지) + 표본 원문(표시·디버깅).
    norm_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    # 계정(예산계정) — 조합 키의 일부라 non-null. acct_code = ERP 예산계정 코드(bgacctCd) 매칭.
    acct_code: Mapped[str] = mapped_column(String(32), nullable=False)
    acct_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 이 (가맹점 × 계정) 조합의 최근성 가중 최빈 적요.
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 이 조합의 총 거래 수(표본 크기) + 최빈적요 지배율(0~1, 가중) + 최근 관측 연도.
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dominance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    last_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<CardSeedNote merchant={self.merchant!r} acct={self.acct_code!r} "
            f"note={self.note!r} n={self.count}>"
        )
