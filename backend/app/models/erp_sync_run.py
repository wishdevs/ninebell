"""ErpSyncRun ORM 모델 — ERP 소스 데이터 동기화 실행 이력(erp_sync_runs).

수동(/admin/erp-sync·/me/catalog/sync)·스케줄러 동기화 1회 = 1행. 진행/성공/실패/건너뜀을
DB 에 남겨 재기동 뒤에도 "마지막으로 언제 무엇이 어떻게 됐는지"를 볼 수 있게 한다(이전에는
erp_code_catalog.synced_at 만 영속이고 실패·조직 반영 결과는 RAM 에만 있었다).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONVariant

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


class ErpSyncRun(Base):
    __tablename__ = "erp_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 'budget_unit' | 'project' | 'partner' | 'org_unit'
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 'manual' | 'scheduled'
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    # running | succeeded | failed | skipped
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # manual 이면 실행자. 사용자 삭제 시 이력은 남기고 NULL.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # via(api|browser) · org_unit 의 applied/reassigned 요약.
    extra: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)

    def __repr__(self) -> str:
        return f"<ErpSyncRun id={self.id} kind={self.kind} status={self.status}>"
