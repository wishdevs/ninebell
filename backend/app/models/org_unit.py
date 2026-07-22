"""조직구분(OrgUnit) + 에이전트 접근(AgentOrgAccess) ORM 모델.

조직구분 = 에이전트 사용 권한을 나누는 조직 단위. 2뎁스 계층: 본부(parent_id IS NULL) → 팀
(parent_id = 본부 id). 관리자가 CRUD 한다. 멤버 배정·에이전트 접근은 **팀(leaf)에만** 허용한다
(본부는 그룹핑·표시용). 팀에는 비용구분(cost_type: 판관비/제조원가)이 붙어 카드 자동화의
예산계정 (판)/(제) 접두사 선택에 쓰인다.
agent_org_access = (agent_id, org_unit_id) 존재 = 그 조직구분(팀)이 그 에이전트를 쓸 수 있음.
'최초 모두 선택'은 agents.access_configured=false 로 표현하고, 그때 GET 은 전체 팀을 반환한다.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# 비용구분 값(팀에만). 카드 자동화에서 예산계정 접두사로 매핑: 판관비→'(판)', 제조원가→'(제)'.
COST_TYPE_SGA = "판관비"
COST_TYPE_MFG = "제조원가"
COST_TYPES = (COST_TYPE_SGA, COST_TYPE_MFG)
COST_TYPE_PREFIX = {COST_TYPE_SGA: "(판)", COST_TYPE_MFG: "(제)"}


class OrgUnit(Base, TimestampMixin):
    __tablename__ = "org_units"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # 본부=NULL, 팀=본부 id. 본부 삭제 시 하위 팀도 CASCADE 삭제.
    parent_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("org_units.id", ondelete="CASCADE"), nullable=True
    )
    # 비용구분(직속 인원 보유 노드에 의미). 판관비|제조원가. 순수 컨테이너(본부 등)는 NULL.
    cost_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # ERP 조직도 인원수(서브트리 합계) — 직속 인원 판별용. (member_count - 직속자식합) > 0 이면 직속 보유.
    member_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<OrgUnit id={self.id} label={self.label!r} parent={self.parent_id}>"


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
