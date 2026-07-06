"""Agent ORM 모델 — 프론트 `src/lib/data/agents.ts` 의 Agent 타입 매핑.

id 는 프론트 픽스처의 슬러그(예: 'outbound-test')를 그대로 보존하려 String PK.
flow_graph 는 분기/루프 그래프(React Flow)로, 계약 Agent JSON 의 flowGraph 필드를
서빙하기 위해 JSONB 컬럼으로 둔다(계약 스키마 컬럼 목록 외 추가 — 보고서에 명시).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONVariant

if TYPE_CHECKING:
    from app.models.agent_group import AgentGroup
    from app.models.agent_intervention import AgentIntervention
    from app.models.agent_log import AgentLog
    from app.models.agent_step import AgentStep


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 실행 레지스트리(app.live.registry) 워크플로우 id. DB agent id(슬러그)와 실행 id 를
    # 잇는 서버측 단일 소스 — 프론트 하드코딩 매핑(WORKFLOW_BY_AGENT) 대체. 없으면 실행 불가.
    workflow_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    # 소속 그룹(2뎁스 분류). NULL = 단독 에이전트. 그룹 삭제 시 단독으로 승격(SET NULL).
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_groups.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 완료 후 사람이 이어서 할 일(핸드오프 안내). 에이전트는 여기까지만 자동화하고, 이후는
    # 사람 몫임을 완료 화면에 안내한다(예: 카드 결의서=저장 후 옴니솔에서 결제 상신). NULL=없음.
    handoff_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # browser | api | hybrid
    drive: Mapped[str] = mapped_column(String(32), nullable=False)
    # readonly | approval | conversational | autonomous
    interaction: Mapped[str] = mapped_column(String(32), nullable=False)
    target_system: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # running | waiting_input | paused | completed | failed | idle
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    flow_graph: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    # 에이전트별 세부설정 저장값(관리자 PATCH). 정의(스키마)는 코드가 단일 소스
    # (app/services/agent_settings.py). NULL = 저장값 없음(스키마 기본값 사용).
    settings: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    # 조직구분 접근이 명시 설정됐는지. false = 최초(전체 조직구분 허용), true = agent_org_access 행이 진실.
    access_configured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # 조직구분 미지정(users.org_unit_id IS NULL) 사용자의 실행 허용 여부.
    # access_configured=true 일 때만 의미(최초 전체 허용 상태는 미지정도 허용).
    allow_unassigned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # 그룹은 에이전트 수가 적어 selectin 1회 추가 조회로 충분(N+1 아님).
    group: Mapped[AgentGroup | None] = relationship(lazy="selectin")

    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        order_by="AgentStep.position",
        lazy="selectin",
    )
    logs: Mapped[list[AgentLog]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        order_by="AgentLog.position",
        lazy="selectin",
    )
    intervention: Mapped[AgentIntervention | None] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Agent id={self.id}>"
