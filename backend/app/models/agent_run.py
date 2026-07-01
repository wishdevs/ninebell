"""AgentRun ORM 모델 — 라이브 실행(run) 요약·이력.

런 요약(상태·소유자·시각·결과·로그)만 서버 권위로 보관한다. 라이브 단계 스크린샷/HITL 은
SSE 로 스트리밍되는 휘발 상태이며 저장하지 않는다. id 는 클라이언트가 만드는 런 식별자
(예: 'run-abc123')를 그대로 쓰고, agent_id 는 워크플로우 식별자(agents 테이블 FK 아님 —
demo-echo 등 미등록 워크플로우도 실행되므로 느슨한 문자열).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONVariant

if TYPE_CHECKING:
    from app.models.user import User


class AgentRun(Base):
    __tablename__ = "agent_runs"

    # 클라이언트가 만든 런 id(세션 키와 동일). 예: 'run-<hex>'.
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # 워크플로우 식별자(FK 아님 — demo-echo 등 미등록 워크플로우 허용).
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # running | waiting | succeeded | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 최종 결과(문자열/구조). 성공 시 result 이벤트 노트, 실패 시 error 사유.
    result: Mapped[dict | list | str | None] = mapped_column(JSONVariant, nullable=True)
    # 런 로그 라인 배열([{ts,level,message}, ...]).
    logs: Mapped[list | None] = mapped_column(JSONVariant, nullable=True, default=list)

    # 실행자(요약의 userDisplayName 조인용). 단방향·eager — 로깅 뷰에서 누가 실행했는지.
    user: Mapped[User] = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return f"<AgentRun id={self.id} status={self.status}>"
