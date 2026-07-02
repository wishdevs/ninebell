"""ErpCodeCatalog ORM 모델 — 공용 ERP 코드 카탈로그(헤드리스 동기화로 채움).

옴니솔 코드피커(예산단위 bg_cd / 프로젝트 pjt_cd)를 헤드리스로 훑어 코드·명칭을 캐시한다.
- 예산단위(budget_unit): 부서 스코프(dept = 로그인 사용자의 부서. 피커가 부서별로 서버필터됨).
- 프로젝트(project): 전사 공용 → dept=''.
PRIMARY KEY (kind, dept, code) 로 upsert. 조회는 인증 사용자 누구나(공용 참조 데이터).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONVariant


class ErpCodeCatalog(Base):
    __tablename__ = "erp_code_catalog"

    # 'budget_unit'(예산단위) | 'project'(프로젝트).
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    # 예산단위=부서명(피커가 부서별 필터). 프로젝트=''(전사 공용).
    dept: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ErpCodeCatalog kind={self.kind} dept={self.dept!r} code={self.code}>"
