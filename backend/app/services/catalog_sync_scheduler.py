"""주기 기반 무인 ERP 소스 데이터 동기화 스케줄러 — lifespan 백그라운드 태스크.

60초 틱마다 4종 kind 각각에 대해 "마지막 실행 시작 시각(erp_sync_runs 최근 행 started_at, 상태
무관 — 실패해도 주기 뒤 재시도) + 항목별 주기(erp_sync_settings, 없으면 기본값)" 가 지났는지
판정하고, 대상 kind 를 순차 실행한다(2026-09-02 자정 고정 → 항목별 주기). 무인 실행이라
사용자 세션(CredCache) 대신 전용 서비스 계정(erp_sync_userid/password)을 쓰고, 수동 동기화와
같은 1슬롯 세마포어·전역 ERP 실행 예산을 공유한다 — 수동 동기화가 슬롯을 쥐고 있으면 그 틱은
건너뛰고 다음 틱에 다시 판정한다(스킵 이력 행은 남기지 않는다). 실행 본체는 services.erp_sync.

기존 reaper 관례(app/live/session.reap_sessions 등)와 동일하게 `while True + asyncio.sleep` 이며
lifespan finally 에서 cancel 된다. api 는 desired_count=1·인메모리 상태라 이 스케줄러도 단일
인스턴스가 옳다(수평 확장 시 별도 잡으로 빼야 함 — CLAUDE.md 배포 주석과 동일 전제).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_sessionmaker
from app.services import erp_sync

logger = logging.getLogger(__name__)

# 판정 주기(초). 주기 선택지의 최소가 1시간이라 60초면 충분히 촘촘하다.
TICK_S = 60


def schedule_status(settings) -> dict:
    """GET /admin/erp-sync 의 schedule 블록 — 설정에서 파생(비밀번호 값은 노출하지 않는다)."""
    configured = erp_sync.service_account(settings) is not None
    enabled = bool(settings.erp_sync_daily_enabled)
    return {
        "enabled": enabled,
        "serviceAccountConfigured": configured,
        "active": enabled and configured,
        "tz": settings.erp_sync_tz,
        "intervalOptions": erp_sync.interval_options(),
    }


async def due_kinds(session: AsyncSession, *, now: datetime | None = None) -> list[str]:
    """이번 틱에 실행할 kind — KINDS 순서. 이력 없음 → 즉시, 마지막 시작 + 주기 ≤ now → 대상."""
    intervals = await erp_sync.load_intervals(session)
    due: list[str] = []
    for kind in erp_sync.KINDS:
        last = await erp_sync.last_started_at(session, kind)
        if erp_sync.is_due(last, intervals[kind], now=now):
            due.append(kind)
    return due


async def tick(app, userid: str, password: str, *, now: datetime | None = None) -> list[str]:
    """한 틱 — 슬롯이 비어 있고 대상 kind 가 있으면 슬롯을 잡고 순차 실행. 실행한 kind 목록을 반환.

    세마포어 반납은 run_kinds 의 finally 가 맡는다. DB 판정 중 수동 동기화가 슬롯을 잡았으면
    이번 틱은 건너뛴다(locked 재확인 → acquire 사이에 await 가 없어 원자적).
    """
    semaphore = app.state.catalog_sync_semaphore
    if semaphore.locked():
        return []
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        due = await due_kinds(session, now=now)
    if not due or semaphore.locked():
        return []
    await semaphore.acquire()
    logger.info("주기 ERP 동기화 시작 — kinds=%s", due)
    await erp_sync.run_kinds(
        app, [(kind, userid, password) for kind in due],
        trigger=erp_sync.TRIGGER_SCHEDULED, sessionmaker=sessionmaker,
    )
    return due


async def run_catalog_sync_scheduler(app) -> None:
    """스케줄러 루프. 설정 미비(비활성·서비스계정 없음)면 조용히 종료한다.

    lifespan 이 asyncio.create_task 로 띄우고 finally 에서 cancel 한다. CancelledError 는 정상 종료.
    틱 내부 예외(DB 등)는 로그로 남기고 다음 틱에 재시도한다 — 루프가 죽어 조용히 멈추지 않게.
    """
    settings = get_settings()
    if not settings.erp_sync_daily_enabled:
        return
    svc = erp_sync.service_account(settings)
    if svc is None:
        logger.warning(
            "ERP 동기화 스케줄러가 켜졌으나 ERP_SYNC_USERID/ERP_SYNC_PASSWORD 가 없습니다 — 비활성"
        )
        return
    userid, password = svc
    logger.info(
        "ERP 동기화 스케줄러 시작 — %d초 틱, 항목별 주기(기본 %s)", TICK_S, erp_sync.DEFAULT_INTERVALS
    )
    try:
        while True:
            await asyncio.sleep(TICK_S)
            try:
                await tick(app, userid, password)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — 틱 실패는 로그로 표면화하고 루프는 유지
                logger.exception("ERP 동기화 스케줄러 틱 실패 — 다음 틱에 재시도")
    except asyncio.CancelledError:  # lifespan 종료 — 정상.
        logger.info("ERP 동기화 스케줄러 종료")
        raise
