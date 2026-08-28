"""일일 무인 코드 카탈로그 동기화 스케줄러 — lifespan 백그라운드 태스크.

하루 1회(erp_sync_at, 서버 로컬 TZ) 예산단위·프로젝트·거래처 카탈로그를 순차 동기화한다.
무인 실행이라 사용자 세션(CredCache) 대신 전용 서비스 계정(erp_sync_userid/password)을 쓰고,
수동 동기화와 같은 1슬롯 세마포어·전역 ERP 실행 예산을 공유한다(경합 시 그 kind 는 건너뛴다).

기존 reaper 관례(app/live/session.reap_sessions 등)와 동일하게 `while True + asyncio.sleep` 이며
lifespan finally 에서 cancel 된다. api 는 desired_count=1·인메모리 상태라 이 스케줄러도 단일
인스턴스가 옳다(수평 확장 시 별도 잡으로 빼야 함 — CLAUDE.md 배포 주석과 동일 전제).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from datetime import datetime, timedelta

from app.config import get_settings
from app.db import get_sessionmaker
from app.services.code_sync import sync_catalog

logger = logging.getLogger(__name__)

# 실행 후 같은 분에 재계산해 즉시 재실행되는 것을 막는 여유 슬립(초).
_POST_RUN_GRACE_S = 60


def _parse_hhmm(value: str) -> tuple[int, int]:
    """"HH:MM" → (hour, minute). 형식 오류면 기본 04:30 으로 폴백(경고)."""
    try:
        hh, mm = value.strip().split(":", 1)
        hour, minute = int(hh), int(mm)
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour, minute
    except (ValueError, AttributeError):
        pass
    logger.warning("ERP_SYNC_AT 형식 오류(%r) — 04:30 으로 폴백", value)
    return 4, 30


def _seconds_until(hour: int, minute: int, *, now: datetime | None = None) -> float:
    """다음 HH:MM 까지 남은 초(오늘 시각이 지났으면 내일)."""
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _guarded_sync(app, kind: str, userid: str, password: str) -> None:
    """1슬롯 세마포어를 잡고 sync_catalog 실행 → 결과/에러를 sync_state[kind] 에 기록.

    수동 동기화가 슬롯을 쥐고 있으면(locked) 이 kind 는 건너뛴다(무인 작업이 사용자 조작을
    막지 않도록). 전역 ERP 실행 예산(run_semaphore)도 함께 점유해 일반 실행 상한을 우회하지 않는다.
    """
    semaphore = app.state.catalog_sync_semaphore
    sync_state = app.state.catalog_sync_state
    run_semaphore = getattr(app.state, "run_semaphore", None)
    browser_factory = getattr(app.state, "browser_factory", None)
    sessionmaker = get_sessionmaker()

    if semaphore.locked():
        logger.info("일일 동기화 건너뜀(kind=%s) — 다른 동기화가 진행 중", kind)
        # 스킵도 관측 가능하게 남긴다(조용한 실패 금지) — sync-status 로 노출된다. error 는
        # 실패가 아니므로 None 을 유지하고 skipped 플래그로 구분한다.
        sync_state[kind] = {"running": False, "error": None, "skipped": True}
        return
    await semaphore.acquire()
    sync_state[kind] = {"running": True, "lastSyncedAt": None, "count": None, "error": None}
    try:
        async with (run_semaphore if run_semaphore is not None else nullcontext()):
            result = await sync_catalog(kind, userid, password, browser_factory, sessionmaker)
        sync_state[kind] = {
            "running": False,
            "lastSyncedAt": result["syncedAt"],
            "count": result["count"],
            "error": None,
            "applied": result.get("applied"),
            "reassigned": result.get("reassigned"),
        }
        logger.info(
            "일일 동기화 완료 kind=%s via=%s count=%s", kind, result.get("via"), result.get("count")
        )
    except Exception as exc:  # noqa: BLE001 — 실패를 상태로 남기고 다음 kind 로.
        logger.exception("일일 동기화 실패(kind=%s)", kind)
        sync_state[kind] = {"running": False, "lastSyncedAt": None, "count": None, "error": str(exc)}
    finally:
        semaphore.release()


async def run_daily_catalog_sync(app) -> None:
    """일일 동기화 루프. 설정 미비(비활성·서비스계정 없음)면 조용히 종료한다.

    lifespan 이 asyncio.create_task 로 띄우고 finally 에서 cancel 한다. CancelledError 는 정상 종료.
    """
    settings = get_settings()
    if not settings.erp_sync_daily_enabled:
        return
    userid, password = settings.erp_sync_userid, settings.erp_sync_password
    if not (userid and password):
        logger.warning(
            "일일 카탈로그 동기화가 켜졌으나 ERP_SYNC_USERID/ERP_SYNC_PASSWORD 가 없습니다 — 비활성"
        )
        return

    hour, minute = _parse_hhmm(settings.erp_sync_at)
    kinds = settings.erp_sync_kind_list()
    logger.info("일일 카탈로그 동기화 스케줄러 시작 — 매일 %02d:%02d, kinds=%s", hour, minute, kinds)
    try:
        while True:
            await asyncio.sleep(_seconds_until(hour, minute))
            logger.info("일일 카탈로그 동기화 시작 — kinds=%s", kinds)
            for kind in kinds:
                await _guarded_sync(app, kind, userid, password)
            await asyncio.sleep(_POST_RUN_GRACE_S)  # 같은 분 재실행 방지.
    except asyncio.CancelledError:  # lifespan 종료 — 정상.
        logger.info("일일 카탈로그 동기화 스케줄러 종료")
        raise
