"""CardLearnedSelection ORM 모델 — 사용자 개입 학습(가맹점 → 선택) 저장.

card-collect 그리드 개입에서 사용자가 확정한 (예산단위·프로젝트·적요) 선택을 **가맹점 단위**로
누적한다. 같은 가맹점을 여러 번 고쳐도 (user_id, norm_merchant) 유니크로 1행에 접히고(count++),
추후 같은/비슷한 가맹점이 나오면 AI 추천 힌트 또는 결정적 프리필로 재사용한다.

⚠ 트랜잭션 단위가 아니라 **가맹점 단위** 누적 — 테이블은 거래 수가 아니라 서로 다른 가맹점
수로만 자란다. 매칭 키(norm_merchant)는 가맹점명 정규화(공백·괄호표기 흡수)로 서버가 채운다.
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

from app.models.base import Base, JSONVariant, UuidPkMixin


class CardLearnedSelection(UuidPkMixin, Base):
    __tablename__ = "card_learned_selections"
    __table_args__ = (
        UniqueConstraint("user_id", "norm_merchant", name="uq_card_learned_user_merchant"),
        Index("ix_card_learned_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 정규화 가맹점명(매칭 키) + 원문(표시·디버깅용).
    norm_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    # 확정 선택 스냅샷(카탈로그 code·조합·wbs 포함) — 재사용 시 그대로 프리필.
    #   budget: {"code","name","bizplanNm","bgacctNm"} | None
    #   project: {"code","name","wbsNo","wbsNm"} | None
    budget: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    project: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 같은 가맹점 재확정 횟수(가중치·결정적 적용 판정에 사용).
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<CardLearnedSelection user={self.user_id} merchant={self.merchant!r} n={self.count}>"
