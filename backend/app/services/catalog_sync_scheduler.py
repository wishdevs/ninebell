"""일일 무인 ERP 소스 데이터 동기화 스케줄러 — lifespan 백그라운드 태스크.

하루 1회(erp_sync_at, erp_sync_tz 기준 — 기본 Asia/Seoul 00:00) 예산단위·프로젝트·거래처·ERP 조직
카탈로그를 순차 동기화한다. 무인 실행이라 사용자 세션(CredCache) 대신 전용 서비스 계정
(erp_sync_userid/password)을 쓰고, 수동 동기화와 같은 1슬롯 세마포어·전역 ERP 실행 예산을
공유한다(경합 시 그 kind 는 건너뛰고 이력에 skipped 로 남긴다). 실행 본체는 services.erp_sync.

기존 reaper 관례(app/live/session.reap_sessions 등)와 동일하게 `while True + asyncio.sleep` 이며
lifespan finally 에서 cancel 된다. api 는 desired_count=1·인메모리 상태라 이 스케줄러도 단일
인스턴스가 옳다(수평 확장 시 별도 잡으로 빼야 함 — CLAUDE.md 배포 주석과 동일 전제).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.db import get_sessionmaker
from app.services import erp_sync

logger = logging.getLogger(__name__)

# 실행 후 같은 분에 재계산해 즉시 재실행되는 것을 막는 여유 슬립(초).
_POST_RUN_GRACE_S = 60
_DEFAULT_TZ = "Asia/Seoul"


def _parse_hhmm(value: str) -> tuple[int, int]:
    """"HH:MM" → (hour, minute). 형식 오류면 기본 00:00 으로 폴백(경고)."""
    try:
        hh, mm = value.strip().split(":", 1)
        hour, minute = int(hh), int(mm)
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour, minute
    except (ValueError, AttributeError):
        pass
    logger.warning("ERP_SYNC_AT 형식 오류(%r) — 00:00 으로 폴백", value)
    return 0, 0


def _zone(name: str) -> tzinfo:
    """zoneinfo 이름 → tzinfo. 알 수 없는 이름이면 Asia/Seoul 로 폴백(경고)."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("ERP_SYNC_TZ 를 알 수 없음(%r) — %s 로 폴백", name, _DEFAULT_TZ)
        return ZoneInfo(_DEFAULT_TZ)


def _next_run(hour: int, minute: int, *, now: datetime) -> datetime:
    """now 기준 다음 HH:MM(오늘 시각이 지났으면 내일). now 의 tzinfo 를 그대로 따른다."""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _seconds_until(
    hour: int, minute: int, *, now: datetime | None = None, tz: tzinfo | None = None
) -> float:
    """다음 HH:MM 까지 남은 초. now 미지정 시 tz 의 현재 시각(tz 도 없으면 서버 로컬)."""
    now = now or datetime.now(tz)
    return (_next_run(hour, minute, now=now) - now).total_seconds()


def schedule_status(settings) -> dict:
    """GET /admin/erp-sync 의 schedule 블록 — 설정에서 파생(비밀번호 값은 노출하지 않는다)."""
    configured = erp_sync.service_account(settings) is not None
    enabled = bool(settings.erp_sync_daily_enabled)
    active = enabled and configured
    next_run_at = None
    if active:
        hour, minute = _parse_hhmm(settings.erp_sync_at)
        tz = _zone(settings.erp_sync_tz)
        next_run_at = _next_run(hour, minute, now=datetime.now(tz)).isoformat()
    return {
        "enabled": enabled,
        "at": settings.erp_sync_at,
        "tz": settings.erp_sync_tz,
        "kinds": settings.erp_sync_kind_list(),
        "serviceAccountConfigured": configured,
        "active": active,
        "nextRunAt": next_run_at,
    }


async def _guarded_sync(app, kind: str, userid: str, password: str) -> None:
    """1슬롯 세마포어를 잡고 kind 1건 실행(공용 러너) — 슬롯 점유 중이면 건너뛰고 skipped 기록.

    수동 동기화가 슬롯을 쥐고 있으면(locked) 이 kind 는 건너뛴다(무인 작업이 사용자 조작을
    막지 않도록). 세마포어 반납은 run_kinds 의 finally 가 맡는다.
    """
    semaphore = app.state.catalog_sync_semaphore
    sessionmaker = get_sessionmaker()
    if semaphore.locked():
        logger.info("일일 동기화 건너뜀(kind=%s) — 다른 동기화가 진행 중", kind)
        await erp_sync.record_skip(
            app, kind, trigger=erp_sync.TRIGGER_SCHEDULED, sessionmaker=sessionmaker
        )
        return
    await semaphore.acquire()
    await erp_sync.run_kinds(
        app, [(kind, userid, password)],
        trigger=erp_sync.TRIGGER_SCHEDULED, sessionmaker=sessionmaker,
    )


async def run_daily_catalog_sync(app) -> None:
    """일일 동기화 루프. 설정 미비(비활성·서비스계정 없음)면 조용히 종료한다.

    lifespan 이 asyncio.create_task 로 띄우고 finally 에서 cancel 한다. CancelledError 는 정상 종료.
    """
    settings = get_settings()
    if not settings.erp_sync_daily_enabled:
        return
    svc = erp_sync.service_account(settings)
    if svc is None:
        logger.warning(
            "일일 ERP 동기화가 켜졌으나 ERP_SYNC_USERID/ERP_SYNC_PASSWORD 가 없습니다 — 비활성"
        )
        return
    userid, password = svc

    hour, minute = _parse_hhmm(settings.erp_sync_at)
    tz = _zone(settings.erp_sync_tz)
    kinds = settings.erp_sync_kind_list()
    logger.info(
        "일일 ERP 동기화 스케줄러 시작 — 매일 %02d:%02d (%s), kinds=%s",
        hour, minute, settings.erp_sync_tz, kinds,
    )
    try:
        while True:
            await asyncio.sleep(_seconds_until(hour, minute, tz=tz))
            logger.info("일일 ERP 동기화 시작 — kinds=%s", kinds)
            for kind in kinds:
                await _guarded_sync(app, kind, userid, password)
            await asyncio.sleep(_POST_RUN_GRACE_S)  # 같은 분 재실행 방지.
    except asyncio.CancelledError:  # lifespan 종료 — 정상.
        logger.info("일일 ERP 동기화 스케줄러 종료")
        raise
