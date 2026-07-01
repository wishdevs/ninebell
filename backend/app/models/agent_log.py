"""AgentLog ORM 모델 — 에이전트 실행 로그(LogEntry).

`key` 가 프론트 log.id(예: 'l1'), `position` 으로 정렬한다. `at` 표시값은 logged_at.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    # info | action | success | warn | error
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    step_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    agent: Mapped[Agent] = relationship(back_populates="logs")
