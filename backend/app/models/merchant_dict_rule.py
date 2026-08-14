"""MerchantDictRule ORM 모델 — 가맹점 분류 사전(하이브리드) 규칙.

미등록 가맹점을 카드 표기명 키워드로 인식해 계정/힌트를 제공하는 규칙을 DB 로 관리한다
(화면에서 추가/수정, 배포 없이). 초기값은 코드 기본 사전(merchant_dict.DEFAULT_RULES)을
마이그레이션이 시드한다. 매칭 로직·키워드 의미는 app.agents.card_collect.merchant_dict 참조.

keywords 는 소문자 부분일치 목록을 콤마(,)로 이어 저장한다(개별 키워드에 콤마 없음).
sort_order 오름차순이 매칭 우선순위(첫 매칭 채택). enabled=False 면 매칭에서 제외한다.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class MerchantDictRule(UuidPkMixin, Base, TimestampMixin):
    __tablename__ = "merchant_dict_rules"

    # 소문자 부분일치 키워드(콤마 구분). 예: "주유소,오일뱅크,칼텍스".
    keywords: Mapped[str] = mapped_column(String(1024), nullable=False)
    # 사람이 읽는 유형(AI 힌트 문구·화면 표시). 예: "주유·유류".
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    # 결정적 해석용 예산단위 계정명(bgacctNm 매칭). 모호하면 NULL(힌트만).
    acct: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # True=결정적 폴백 후보(계정 확정), False=AI 힌트만.
    strong: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # 출처: '내부'·'웹'·'내부+웹'·'큐레이션' 등(관리·감사용).
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="큐레이션")
    # 매칭 우선순위(오름차순, 첫 매칭 채택) + 비활성 토글.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
