"""AgentTemplate ORM 모델 — 대화형 실행에서 누적한 selections 를 이름 붙여 저장·재생한다.

대화형(chat_form) 실행이 끝나면 프론트가 그때 누적된 ChatSelection[] 을 이름과 함께
저장한다(POST /runs/templates). 이후 그 템플릿으로 AUTO 재생(POST /runs/collect
{templateId})하면 대화 없이 selections 를 순서대로 그대로 적용한다.

selections 는 chat_form 이 만든 구조와 동일: [{"tool","field","value","query"?}, ...].
소유자(user_id)만 조회·삭제·재생할 수 있다(요청 라우터에서 스코프).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONVariant


class AgentTemplate(Base):
    __tablename__ = "agent_templates"

    # 클라이언트가 만든 템플릿 id(예: 'tpl-<hex>'). agent_runs.id 처럼 문자열 PK.
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # 워크플로우 식별자(FK 아님 — agent_runs 와 동일한 느슨한 문자열).
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # 누적된 ChatSelection[] — [{"tool","field","value","query"?}, ...].
    selections: Mapped[list | None] = mapped_column(JSONVariant, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AgentTemplate id={self.id} agent={self.agent_id} name={self.name}>"
