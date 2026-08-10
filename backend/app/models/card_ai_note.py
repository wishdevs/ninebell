"""CardAiNote ORM 모델 — (가맹점 × 계정) → AI 생성 적요 캐시.

학습(개인)·seed(전사)에 **없는** (가맹점 × 계정) 조합에서만 Gemini 로 계정 맞춤 적요를
1회 생성하고 이 표에 적재한다. 이후 같은 조합은 LLM 재호출 없이 즉시 반환(전사 공유 캐시).

예: 네이버파이낸셜은 카드이력상 '해외출장 숙박비'가 압도적이지만, 사람이 예산단위를
'회의비' 계정으로 바꾸면 seed/category 에 그 조합이 없어 결정적 매칭이 실패한다 — 이때
계정 이름(회의비)+가맹점명으로 AI 가 적요를 생성해 여기에 캐시한다.

⚠ 트랜잭션이 아니라 **(가맹점 × 계정)** 조합 단위 1행 — 유니크 `(norm_merchant, acct_code)`.
매칭 키(norm_merchant)는 개인 학습/seed 와 동일한 정규화를 쓴다. 사용자별이 아니라 전사 공유
(계정 맞춤 적요는 특정 사용자에 종속되지 않음). acct_name/model 은 감사·재생성 판단용.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class CardAiNote(UuidPkMixin, Base):
    __tablename__ = "card_ai_notes"
    __table_args__ = (
        UniqueConstraint("norm_merchant", "acct_code", name="uq_card_ai_note_merchant_acct"),
        Index("ix_card_ai_note_merchant", "norm_merchant"),
    )

    # 정규화 가맹점명(매칭 키, seed/learned 와 동일 정규화) + 표본 원문(표시·디버깅).
    norm_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    # 계정(예산계정) — 조합 키의 일부라 non-null. acct_code = ERP 예산계정 코드(bgacctCd) 매칭.
    acct_code: Mapped[str] = mapped_column(String(32), nullable=False)
    # 생성 근거로 쓴 계정 이름(감사) — 프론트가 넘긴 bgacctNm.
    acct_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AI 가 생성한 계정 맞춤 적요.
    note: Mapped[str] = mapped_column(String(255), nullable=False)
    # 생성 모델(감사·재생성 판단용).
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<CardAiNote merchant={self.merchant!r} acct={self.acct_code!r} note={self.note!r}>"
        )
