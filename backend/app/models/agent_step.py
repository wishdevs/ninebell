"""AgentStep ORM 모델 — 워크플로우 단계(WorkflowStep).

`key` 가 프론트 step.id(예: 'login') 이며 에이전트 내에서만 고유하다(전역 PK 는 surrogate uuid).
substeps 는 [{label,status}] 리스트로 JSONB(계약 컬럼 외 추가 — Agent JSON 의 substeps 서빙용).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONVariant

if TYPE_CHECKING:
    from app.models.agent import Agent


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    skill: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # done | active | pending | error
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    substeps: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="steps")
