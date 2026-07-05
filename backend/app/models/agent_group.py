"""AgentGroup ORM 모델 — 에이전트 그룹(2뎁스 고정).

그룹은 실행 불가한 순수 분류/내비 단위다. 실행 allowlist·조직접근·즐겨찾기·런 기록은
전부 에이전트 단위 그대로이며, 그룹은 목록 섹션·브레드크럼 표기에만 쓰인다.
id 는 슬러그(예: 'resolution') String PK — Agent.id 와 동일 관례.
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentGroup(Base):
    __tablename__ = "agent_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AgentGroup id={self.id}>"
