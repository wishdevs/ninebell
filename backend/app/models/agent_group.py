"""AgentGroup ORM 모델 — 에이전트 그룹(2뎁스 고정).

그룹은 실행 불가한 분류/내비 단위이면서, 2026-08-31 부터 **조직접근 게이트의 상위 층**이다:
그룹에 접근이 설정되면(access_configured) 조직구분이 그룹 게이트를 통과해야 그 그룹의
에이전트가 보인다/실행된다(그룹 AND 에이전트 — agent_visibility.is_visible 단일 판정식).
실행 allowlist·즐겨찾기·런 기록은 여전히 에이전트 단위다.
id 는 슬러그(예: 'resolution') String PK — Agent.id 와 동일 관례.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentGroup(Base):
    __tablename__ = "agent_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 그룹 조직접근(에이전트의 동명 컬럼과 대칭) — false(최초) = 전체 허용.
    access_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 조직구분 미지정(org_unit_id IS NULL) 사용자 허용 여부 — access_configured=True 일 때만 의미.
    allow_unassigned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<AgentGroup id={self.id}>"


class AgentGroupOrgAccess(Base):
    """에이전트 그룹 × 조직구분 허용 매핑. 행 존재 = 허용(AgentOrgAccess 와 대칭)."""

    __tablename__ = "agent_group_org_access"
    __table_args__ = (Index("ix_agent_group_org_access_org_unit_id", "org_unit_id"),)

    group_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_groups.id", ondelete="CASCADE"), primary_key=True
    )
    org_unit_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("org_units.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<AgentGroupOrgAccess group={self.group_id} org={self.org_unit_id}>"
