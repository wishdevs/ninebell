"""AgentIntervention ORM 모델 — 사람 개입(HITL) 상태(Intervention).

에이전트당 최대 1개(agent_id UNIQUE). options(choice)/messages(chat) 는 JSONB.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONVariant

if TYPE_CHECKING:
    from app.models.agent import Agent


class AgentIntervention(Base):
    __tablename__ = "agent_interventions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # choice | chat
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    messages: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    placeholder: Mapped[str | None] = mapped_column(String(512), nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="intervention")
