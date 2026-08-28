"""PurchaseOrderPlan ORM 모델 — 구매발주 계획서 확정본 보관.

purchase-order 런의 계획서 HITL 에서 사용자가 최종 제출·검증 통과한 계획(confirmed_plan)을
그대로 스냅샷한다. 목록·검색용 파생 컬럼(프로젝트·WBS·발주단위 수·합계 금액)은 저장 시
plan JSON 에서 계산해 채운다. run_id 는 agent_runs 와 느슨하게 연결(FK 아님 — 런 이력이
정리돼도 계획서는 남는다).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONVariant, TimestampMixin, UuidPkMixin
from app.models.user import User


class PurchaseOrderPlan(UuidPkMixin, Base, TimestampMixin):
    __tablename__ = "purchase_order_plans"
    __table_args__ = (Index("ix_purchase_order_plans_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wbs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 파생값 — plan.units 길이 / 모든 vendorGroups[].amount 합.
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 제출 계획서 원본(PlanIn shape) + 읽은 BOM 요약.
    plan: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    bom_summary: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)

    user: Mapped[User] = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<PurchaseOrderPlan user={self.user_id} project={self.project_code!r} "
            f"units={self.unit_count}>"
        )
