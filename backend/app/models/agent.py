"""Agent ORM 모델 — 프론트 `src/lib/data/agents.ts` 의 Agent 타입 매핑.

id 는 프론트 픽스처의 슬러그(예: 'outbound-test')를 그대로 보존하려 String PK.
flow_graph 는 분기/루프 그래프(React Flow)로, 계약 Agent JSON 의 flowGraph 필드를
서빙하기 위해 JSONB 컬럼으로 둔다(계약 스키마 컬럼 목록 외 추가 — 보고서에 명시).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONVariant

if TYPE_CHECKING:
    from app.models.agent_intervention import AgentIntervention
    from app.models.agent_log import AgentLog
    from app.models.agent_step import AgentStep


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

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
