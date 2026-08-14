"""CardSeedSelection ORM 모델 — 전사 기초자료(가맹점 → 계정·적요) 집계 저장.

법인카드 3년치 거래 엑셀(수천 행)을 **가맹점 단위로 집계**해 담는다. 개인 학습
(card_learned_selections)이 없을 때의 **전사 폴백 tier**로, 같은 가맹점에 대한 과거 전사
최빈 계정·적요를 AI 추천 힌트로 제공한다.

⚠ 트랜잭션이 아니라 **가맹점 단위** 1행(거래 수가 아니라 서로 다른 가맹점 수로만 성장,
실측 8,826거래→1,048가맹점). user_id 없음(전사 공용). 매칭 키(norm_merchant)는 개인 학습과
동일한 정규화를 쓴다. dominance = 최근성 가중 최빈계정 비율(신뢰도), last_year = 최근 관측 연도.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class CardSeedSelection(UuidPkMixin, Base, TimestampMixin):
    __tablename__ = "card_seed_selections"
    __table_args__ = (
        UniqueConstraint("norm_merchant", name="uq_card_seed_merchant"),
    )

    # 정규화 가맹점명(매칭 키, 지점 단위 유지) + 표본 원문(표시·디버깅).
    norm_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    # 최근성 가중 최빈 계정과목(ERP 예산계정 bgacctNm 매칭에 쓰는 계정명) + 코드.
    acct_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    acct_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 최근성 가중 최빈 적요.
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 총 거래 수(표본 크기) + 최빈계정 지배율(0~1, 가중) + 최근 관측 연도.
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dominance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    last_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<CardSeedSelection merchant={self.merchant!r} acct={self.acct_name!r} n={self.count}>"
