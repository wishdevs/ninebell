"""ERP 소스 데이터 동기화 공용 러너 — 수동(/me/catalog/sync·/admin/erp-sync)·스케줄러가 공유.

한 곳에 모은 것: 1슬롯 세마포어(app.state.catalog_sync_semaphore) 획득/반납, RAM 상태
(app.state.catalog_sync_state[kind] — 기존 /me/catalog/sync-status 응답 형태 그대로) 갱신,
erp_sync_runs 이력 행 open/close(+건너뜀 기록), 전역 ERP 실행 예산(run_semaphore) 점유,
sync_catalog 호출. 이전에는 me_codes._run_catalog_sync 와 catalog_sync_scheduler._guarded_sync
가 같은 절차를 각자 들고 있었고 이력은 RAM 에만 남았다.

자격증명 결정(resolve_credentials)도 여기 둔다 — 세션 CredCache 비밀번호(실 ERP 로그인 관리자)
우선, 없으면 서비스 계정(ERP_SYNC_USERID/PASSWORD) 폴백. 로컬 계정(password_hash 있음, admin)의
세션 비밀번호는 ERP 자격증명이 아니라 어느 kind 든 서비스 계정만 후보다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import ErpSyncRun, ErpSyncSetting
from app.models.erp_sync_run import STATUS_FAILED, STATUS_RUNNING, STATUS_SUCCEEDED
from app.services.code_sync import sync_catalog

logger = logging.getLogger(__name__)

# 동기화 kind — me_codes._VALID_KINDS 와 동일 집합·순서(화면 표시 순서).
KINDS: tuple[str, ...] = ("budget_unit", "project", "partner", "org_unit")
KIND_LABELS: dict[str, str] = {
    "budget_unit": "예산단위",
    "project": "프로젝트",
    "partner": "거래처",
    "org_unit": "ERP 조직",
}

TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"

# 항목별 동기화 주기 선택지(초, 고정 7종) — GET schedule.intervalOptions·PATCH 검증의 단일 소스.
INTERVAL_OPTIONS: tuple[tuple[int, str], ...] = (
    (3600, "1시간"),
    (21600, "6시간"),
    (43200, "12시간"),
    (86400, "하루"),
    (259200, "3일"),
    (604800, "일주일"),
    (2592000, "한달"),
)
INTERVAL_SECONDS: frozenset[int] = frozenset(s for s, _ in INTERVAL_OPTIONS)
# erp_sync_settings 행이 없을 때의 기본 주기.
DEFAULT_INTERVALS: dict[str, int] = {
    "budget_unit": 3600,
    "project": 3600,
    "partner": 3600,
    "org_unit": 604800,
}

BUSY_MSG = "동기화가 이미 진행 중입니다."
NO_CREDENTIALS_MSG = "세션에 자격증명이 없습니다. 다시 로그인해 주세요."
ORG_UNIT_NEEDS_ERP_ACCOUNT_MSG = (
    "조직도 불러오기는 실제 ERP 계정으로 로그인한 관리자만 사용할 수 있습니다. "
    "로컬 admin 계정은 ERP 로그인이 없어 조직도를 가져올 수 없습니다."
)
# 로컬 계정(admin)은 ERP 로그인이 없어 세션 비밀번호를 쓸 수 없고 서비스 계정만 후보다.
LOCAL_ACCOUNT_NEEDS_SERVICE_MSG = (
    "로컬 계정은 ERP 로그인이 없어 동기화할 수 없습니다. 서비스 계정(ERP_SYNC_USERID/"
    "ERP_SYNC_PASSWORD)을 설정하거나 실제 ERP 계정으로 로그인해 주세요."
)
STALE_RUN_ERROR = "서버 재기동으로 중단됨"

# 백그라운드 태스크 강참조 — 무참조 태스크는 GC 대상이라 실행 중 소멸하면 브라우저 누수 +
# 세마포어 미반납으로 영구 409 가 될 수 있다.
_TASKS: set[asyncio.Task] = set()

# (kind, userid, password) — run_kinds 가 순차 실행하는 작업 단위.
SyncJob = tuple[str, str, str]


# ── 자격증명 ──────────────────────────────────────────────────────────────────
class CredentialError(Exception):
    """동기화에 쓸 자격증명이 없다 — status_code(400|409) 와 사용자 메시지."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def service_account(settings=None) -> tuple[str, str] | None:
    """서비스 계정(ERP_SYNC_USERID/PASSWORD) — 둘 다 있을 때만."""
    settings = settings or get_settings()
    if settings.erp_sync_userid and settings.erp_sync_password:
        return settings.erp_sync_userid, settings.erp_sync_password
    return None


def _erp_session_password(user, session_password: str | None) -> str | None:
    """세션 비밀번호가 ERP 자격증명일 때만 — 로컬 계정(password_hash 있음, 예: admin)의 세션
    비밀번호는 대시보드 로컬 비밀번호라 ERP 로그인에 쓸 수 없다."""
    if session_password and user.password_hash is None:
        return session_password
    return None


def credential_source(user, session_password: str | None, settings=None) -> str | None:
    """이 사용자가 '지금 동기화'를 누르면 쓰일 자격증명 — 'session' | 'service' | None."""
    if _erp_session_password(user, session_password):
        return "session"
    if service_account(settings):
        return "service"
    return None


def resolve_credentials(
    kind: str, user, session_password: str | None, settings=None
) -> tuple[str, str, str]:
    """(userid, password, source). 세션(실 ERP 계정) 우선 → 서비스 계정 폴백. 없으면 CredentialError.

    로컬 계정 세션은 어느 kind 든 ERP 로그인이 안 되므로 서비스 계정만 후보다. 둘 다 없으면
    org_unit + 로컬 계정은 400(기존 문구), 그 외 로컬 계정은 409(서비스 계정 안내), 실 ERP
    계정은 409(재로그인 안내).
    """
    erp_password = _erp_session_password(user, session_password)
    if erp_password:
        return user.omnisol_userid, erp_password, "session"
    svc = service_account(settings)
    if svc:
        return svc[0], svc[1], "service"
    if user.password_hash is not None:
        if kind == "org_unit":
            raise CredentialError(400, ORG_UNIT_NEEDS_ERP_ACCOUNT_MSG)
        raise CredentialError(409, LOCAL_ACCOUNT_NEEDS_SERVICE_MSG)
    raise CredentialError(409, NO_CREDENTIALS_MSG)


# ── 주기 설정 + 실행 판정 ────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """timestamptz 정규화 — SQLite(테스트)는 naive 로 돌려주므로 UTC 로 간주한다."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def interval_options() -> list[dict]:
    return [{"seconds": s, "label": label} for s, label in INTERVAL_OPTIONS]


async def load_intervals(session: AsyncSession) -> dict[str, int]:
    """kind → 주기(초). 저장값이 없으면 기본값."""
    rows = (await session.execute(select(ErpSyncSetting))).scalars().all()
    intervals = dict(DEFAULT_INTERVALS)
    for row in rows:
        if row.kind in intervals:
            intervals[row.kind] = row.interval_seconds
    return intervals


async def save_interval(
    session: AsyncSession, kind: str, seconds: int, *, updated_by: uuid.UUID | None = None
) -> None:
    """kind 주기 upsert + commit. 값 검증(INTERVAL_SECONDS)은 호출자(라우터 422) 몫."""
    row = await session.get(ErpSyncSetting, kind)
    if row is None:
        session.add(
            ErpSyncSetting(
                kind=kind, interval_seconds=seconds, updated_at=_now(), updated_by=updated_by
            )
        )
    else:
        row.interval_seconds = seconds
        row.updated_at = _now()
        row.updated_by = updated_by
    await session.commit()


async def last_started_at(session: AsyncSession, kind: str) -> datetime | None:
    """kind 의 마지막 실행 **시작** 시각(상태 무관 — 실패해도 주기 뒤 재시도)."""
    dt = (
        await session.execute(
            select(func.max(ErpSyncRun.started_at)).where(ErpSyncRun.kind == kind)
        )
    ).scalar()
    return _aware(dt)


def next_run_at(
    last_started: datetime | None, interval_seconds: int, *, now: datetime | None = None
) -> datetime:
    """다음 실행 시각 = 마지막 실행 시작 + 주기. 이력이 없으면 지금(즉시 대상)."""
    now = now or _now()
    if last_started is None:
        return now
    return _aware(last_started) + timedelta(seconds=interval_seconds)


def is_due(
    last_started: datetime | None, interval_seconds: int, *, now: datetime | None = None
) -> bool:
    now = now or _now()
    return next_run_at(last_started, interval_seconds, now=now) <= now


# ── RAM 상태 + 이력 행 ─────────────────────────────────────────────────────────


def _state(app) -> dict:
    return app.state.catalog_sync_state


def mark_running(app, kind: str) -> None:
    _state(app)[kind] = {"running": True, "lastSyncedAt": None, "count": None, "error": None}


async def open_run(
    sessionmaker: async_sessionmaker,
    kind: str,
    trigger: str,
    actor_user_id: uuid.UUID | None = None,
) -> int:
    """status=running 이력 행 생성 → id."""
    async with sessionmaker() as s:
        row = ErpSyncRun(
            kind=kind,
            trigger=trigger,
            status=STATUS_RUNNING,
            started_at=_now(),
            actor_user_id=actor_user_id,
        )
        s.add(row)
        await s.commit()
        return row.id


async def _close_run(
    sessionmaker: async_sessionmaker,
    run_id: int,
    *,
    status: str,
    count: int | None = None,
    error: str | None = None,
    extra: dict | None = None,
) -> None:
    async with sessionmaker() as s:
        await s.execute(
            update(ErpSyncRun)
            .where(ErpSyncRun.id == run_id)
            .values(status=status, finished_at=_now(), count=count, error=error, extra=extra)
        )
        await s.commit()


async def reconcile_stale_runs(sessionmaker: async_sessionmaker) -> int:
    """기동 시 status=running 잔존 행을 failed 로 닫는다(재기동으로 태스크가 사라진 실행).

    api 는 단일 인스턴스(desired_count=1)라 기동 시점에 running 인 행은 전부 죽은 실행이다.
    """
    async with sessionmaker() as s:
        result = await s.execute(
            update(ErpSyncRun)
            .where(ErpSyncRun.status == STATUS_RUNNING)
            .values(status=STATUS_FAILED, finished_at=_now(), error=STALE_RUN_ERROR)
        )
        await s.commit()
        n = result.rowcount or 0
    if n:
        logger.warning("ERP 동기화 이력 정리 — 재기동으로 중단된 running %d건을 failed 로 닫음", n)
    return n


# ── 실행 ──────────────────────────────────────────────────────────────────────
async def execute_kind(
    app,
    kind: str,
    userid: str,
    password: str,
    *,
    trigger: str,
    sessionmaker: async_sessionmaker,
    actor_user_id: uuid.UUID | None = None,
    run_id: int | None = None,
) -> bool:
    """kind 1건 동기화 — 세마포어를 **이미 쥔 채** 호출한다. 성공 여부를 반환(예외를 상태로 남김).

    RAM running → (이력 행 open, 없으면) → run_semaphore 점유 + sync_catalog → RAM/이력 close.
    전역 ERP 실행 예산(run_semaphore)을 함께 점유해 동기화가 일반 실행 상한을 우회하지 않는다.
    """
    state = _state(app)
    mark_running(app, kind)
    if run_id is None:
        run_id = await open_run(sessionmaker, kind, trigger, actor_user_id)
    run_semaphore = getattr(app.state, "run_semaphore", None)
    browser_factory = getattr(app.state, "browser_factory", None)
    try:
        async with run_semaphore if run_semaphore is not None else nullcontext():
            result = await sync_catalog(kind, userid, password, browser_factory, sessionmaker)
    except Exception as exc:  # noqa: BLE001 — 백그라운드 실패를 상태·이력으로 남긴다
        logger.exception("ERP 동기화 실패(kind=%s trigger=%s)", kind, trigger)
        state[kind] = {"running": False, "lastSyncedAt": None, "count": None, "error": str(exc)}
        await _close_run(sessionmaker, run_id, status=STATUS_FAILED, error=str(exc))
        return False
    state[kind] = {
        "running": False,
        "lastSyncedAt": result["syncedAt"],
        "count": result["count"],
        "error": None,
        # org_unit 만 채워진다(다른 kind 는 None) — 프론트가 조직구분 반영 요약을 읽는다.
        "applied": result.get("applied"),
        "reassigned": result.get("reassigned"),
    }
    extra = {k: result[k] for k in ("via", "applied", "reassigned") if result.get(k) is not None}
    await _close_run(
        sessionmaker, run_id, status=STATUS_SUCCEEDED, count=result["count"], extra=extra or None
    )
    logger.info(
        "ERP 동기화 완료 kind=%s trigger=%s via=%s count=%s",
        kind, trigger, result.get("via"), result.get("count"),
    )
    return True


async def run_kinds(
    app,
    jobs: list[SyncJob],
    *,
    trigger: str,
    sessionmaker: async_sessionmaker,
    actor_user_id: uuid.UUID | None = None,
    run_ids: dict[str, int] | None = None,
) -> None:
    """세마포어를 쥔 채 진입 → kind 순차 실행 → finally 에서 세마포어 반납. 백그라운드 태스크 본체."""
    run_ids = run_ids or {}
    try:
        for kind, userid, password in jobs:
            try:
                await execute_kind(
                    app, kind, userid, password,
                    trigger=trigger, sessionmaker=sessionmaker,
                    actor_user_id=actor_user_id, run_id=run_ids.get(kind),
                )
            except Exception as exc:  # noqa: BLE001 — 이력 기록 자체가 실패해도 다음 kind 로
                logger.exception("ERP 동기화 이력 기록 실패(kind=%s)", kind)
                _state(app)[kind] = {
                    "running": False, "lastSyncedAt": None, "count": None, "error": str(exc),
                }
    finally:
        app.state.catalog_sync_semaphore.release()


async def launch(
    app,
    jobs: list[SyncJob],
    *,
    trigger: str,
    actor_user_id: uuid.UUID | None = None,
    sessionmaker: async_sessionmaker | None = None,
) -> bool:
    """수동 트리거 진입점 — 1슬롯 획득 → 첫 kind 이력 행 open + RAM running → 백그라운드 태스크.

    슬롯이 점유 중이면 False(라우터가 409). 획득 뒤 이력 open 이 실패하면 슬롯을 되돌리고 raise.
    이후 kind 의 이력 행은 태스크가 차례에 도달할 때 연다.
    """
    semaphore = app.state.catalog_sync_semaphore
    if semaphore.locked():
        return False
    await semaphore.acquire()
    sessionmaker = sessionmaker or get_sessionmaker()
    first = jobs[0][0]
    try:
        run_id = await open_run(sessionmaker, first, trigger, actor_user_id)
        mark_running(app, first)
    except BaseException:
        semaphore.release()
        raise
    task = asyncio.create_task(
        run_kinds(
            app, jobs,
            trigger=trigger, sessionmaker=sessionmaker,
            actor_user_id=actor_user_id, run_ids={first: run_id},
        )
    )
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return True
