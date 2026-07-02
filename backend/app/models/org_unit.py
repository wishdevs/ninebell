"""조직구분(OrgUnit) + 에이전트 접근(AgentOrgAccess) ORM 모델.

조직구분 = 에이전트 사용 권한을 나누는 조직 단위(임원실·경영본부 등). 관리자가 CRUD 한다.
agent_org_access = (agent_id, org_unit_id) 존재 = 그 조직구분이 그 에이전트를 쓸 수 있음(allow).
'최초 모두 선택'은 agents.access_configured=false 로 표현하고, 그때 GET 은 전체 조직구분을 반환한다
(명시 설정 전이면 전체 허용). PATCH 시 access_configured=true + 명시 행으로 교체.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrgUnit(Base):
    __tablename__ = "org_units"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<OrgUnit id={self.id} label={self.label!r}>"


class AgentOrgAccess(Base):
    """에이전트 × 조직구분 허용 매핑. 행 존재 = 허용."""

    __tablename__ = "agent_org_access"
    # 조직구분 기준 역조회(어떤 에이전트가 이 조직에 허용됐나) 대비 인덱스. (agent_id,org_unit_id)
    # 순서 PK 는 org_unit_id 선두 조회를 못 타므로 별도 인덱스.
    __table_args__ = (Index("ix_agent_org_access_org_unit_id", "org_unit_id"),)

    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    org_unit_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("org_units.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<AgentOrgAccess agent={self.agent_id} org={self.org_unit_id}>"
