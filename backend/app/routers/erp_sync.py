"""ERP 동기화 통합 관리 라우터 (관리자+) — /admin/erp-sync.

관리자 화면 하나에서 ERP 소스 데이터 4종(예산단위·프로젝트·거래처·ERP 조직)의 마지막 동기화
시각·최근 실행 결과를 보고 즉시 동기화한다. 실행 본체·자격증명 폴백은 services.erp_sync,
스케줄 상태는 services.catalog_sync_scheduler.schedule_status. 응답은 프론트 규약대로 camelCase.

- GET  /admin/erp-sync            : 스케줄 상태 + 이 관리자의 자격증명 소스 + kind 별 현황.
- POST /admin/erp-sync/all        : 4종 순차(한 태스크) → 202.
- POST /admin/erp-sync/{kind}     : 단건 → 202. 세션 비밀번호 우선, 서비스 계정 폴백.
- GET  /admin/erp-sync/runs       : 실행 이력 최신순(kind·limit).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

import app.db as appdb
from app.config import get_settings
from app.core.creds import omnisol_password
from app.core.deps import DbSession, RequireAdmin
from app.models import ErpCodeCatalog, ErpSyncRun, User
from app.models.erp_sync_run import STATUS_SUCCEEDED
from app.services import erp_sync
from app.services.catalog_sync_scheduler import schedule_status

router = APIRouter(prefix="/admin/erp-sync", tags=["erp-sync"])


def _iso(dt: datetime | None) -> str | None:
    """timestamptz → ISO(오프셋 포함). SQLite(테스트)는 naive 로 돌려주므로 UTC 로 간주한다."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _run_dict(run: ErpSyncRun, actor_name: str | None) -> dict:
    extra = run.extra or {}
    return {
        "id": run.id,
        "kind": run.kind,
        "trigger": run.trigger,
        "status": run.status,
        "startedAt": _iso(run.started_at),
        "finishedAt": _iso(run.finished_at),
        "count": run.count,
        "error": run.error,
        "applied": extra.get("applied"),
        "reassigned": extra.get("reassigned"),
        "actorName": actor_name if run.trigger == erp_sync.TRIGGER_MANUAL else None,
    }


def _runs_query(kind: str | None):
    stmt = select(ErpSyncRun, User.display_name).outerjoin(User, User.id == ErpSyncRun.actor_user_id)
    if kind:
        stmt = stmt.where(ErpSyncRun.kind == kind)
    return stmt.order_by(ErpSyncRun.started_at.desc(), ErpSyncRun.id.desc())


async def _kind_item(db, sync_state: dict, kind: str) -> dict:
    count = (
        await db.execute(
            select(func.count()).select_from(ErpCodeCatalog).where(ErpCodeCatalog.kind == kind)
        )
    ).scalar() or 0
    last_success = (
        await db.execute(
            select(func.max(ErpSyncRun.finished_at)).where(
                ErpSyncRun.kind == kind, ErpSyncRun.status == STATUS_SUCCEEDED
            )
        )
    ).scalar()
    if last_success is None:
        # 이력 도입(0039) 이전 동기화분 — 카탈로그 synced_at 폴백.
        last_success = (
            await db.execute(
                select(func.max(ErpCodeCatalog.synced_at)).where(ErpCodeCatalog.kind == kind)
            )
        ).scalar()
    last = (await db.execute(_runs_query(kind).limit(1))).first()
    return {
        "kind": kind,
        "label": erp_sync.KIND_LABELS[kind],
        "running": bool((sync_state.get(kind) or {}).get("running")),
        "count": count,
        "lastSuccessAt": _iso(last_success),
        "lastRun": _run_dict(last[0], last[1]) if last else None,
    }


@router.get("")
async def overview(request: Request, user: RequireAdmin, db: DbSession) -> dict:
    settings = get_settings()
    sync_state = getattr(request.app.state, "catalog_sync_state", {})
    items = [await _kind_item(db, sync_state, kind) for kind in erp_sync.KINDS]
    return {
        "schedule": schedule_status(settings),
        "credentialSource": erp_sync.credential_source(user, omnisol_password(request), settings),
        "items": items,
    }


@router.get("/runs")
async def list_runs(
    user: RequireAdmin,
    db: DbSession,
    kind: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    if kind is not None and kind not in erp_sync.KINDS:
        return JSONResponse({"error": f"알 수 없는 kind: {kind}"}, status_code=422)
    rows = (await db.execute(_runs_query(kind).limit(limit))).all()
    return {"items": [_run_dict(run, name) for run, name in rows]}


def _resolve_jobs(request: Request, user, kinds: tuple[str, ...]) -> list[erp_sync.SyncJob]:
    """kind 별 자격증명 결정 — 하나라도 불가하면 CredentialError(전체 요청 거절)."""
    settings = get_settings()
    password = omnisol_password(request)
    jobs: list[erp_sync.SyncJob] = []
    for kind in kinds:
        userid, pw, _source = erp_sync.resolve_credentials(kind, user, password, settings)
        jobs.append((kind, userid, pw))
    return jobs


async def _start(request: Request, user, kinds: tuple[str, ...]):
    try:
        jobs = _resolve_jobs(request, user, kinds)
    except erp_sync.CredentialError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)
    started = await erp_sync.launch(
        request.app, jobs,
        trigger=erp_sync.TRIGGER_MANUAL, actor_user_id=user.id,
        sessionmaker=appdb.get_sessionmaker(),
    )
    if not started:
        return JSONResponse({"error": erp_sync.BUSY_MSG}, status_code=409)
    return None


# /all 을 /{kind} 보다 먼저 선언한다(경로 매칭은 선언 순).
@router.post("/all", status_code=status.HTTP_202_ACCEPTED)
async def sync_all(request: Request, user: RequireAdmin):
    """4종을 한 백그라운드 태스크에서 순차 실행(각 kind 별 이력 행). 진행 중이면 409."""
    err = await _start(request, user, erp_sync.KINDS)
    if err is not None:
        return err
    return {"started": True, "kinds": list(erp_sync.KINDS)}


@router.post("/{kind}", status_code=status.HTTP_202_ACCEPTED)
async def sync_kind(kind: str, request: Request, user: RequireAdmin):
    """단건 동기화. 세션 CredCache 비밀번호 우선, 없으면 서비스 계정 폴백(둘 다 없으면 409/400)."""
    if kind not in erp_sync.KINDS:
        return JSONResponse({"error": f"알 수 없는 kind: {kind}"}, status_code=422)
    err = await _start(request, user, (kind,))
    if err is not None:
        return err
    return {"started": True}
