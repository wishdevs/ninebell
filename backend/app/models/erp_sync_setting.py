"""ErpSyncSetting ORM 모델 — ERP 소스 데이터 동기화 항목(kind)별 주기 설정(erp_sync_settings).

관리자가 /manage/erp-sync 에서 항목마다 고른 주기(초). 행이 없으면 services.erp_sync 의 기본값
(예산단위·프로젝트·거래처 1시간, ERP 조직 일주일). 스케줄러가 매 틱 이 값과 erp_sync_runs 의
마지막 실행 시작 시각으로 실행 여부를 판정한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ErpSyncSetting(Base):
    __tablename__ = "erp_sync_settings"

    # 'budget_unit' | 'project' | 'partner' | 'org_unit'
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    # 허용값은 erp_sync.INTERVAL_OPTIONS 7종(3600~2592000).
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<ErpSyncSetting kind={self.kind} interval={self.interval_seconds}s>"
