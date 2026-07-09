"""내 즐겨찾기 ERP 코드 + 공용 코드 카탈로그 + 헤드리스 동기화 라우터.

- /me/favorites        : 사용자별 즐겨찾는 예산단위/프로젝트 코드 CRUD + 순서변경(소유자 스코프).
- /me/catalog          : 공용 코드 카탈로그 조회(예산단위는 부서 스코프, 프로젝트는 전사).
- /me/catalog/sync     : 카탈로그 헤드리스 동기화 트리거(1슬롯 세마포어, 백그라운드 태스크).
모든 엔드포인트 인증(get_current_user) 필요. 응답은 프론트 규약대로 camelCase.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import nullcontext
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

import app.db as appdb
from app.core.deps import SESSION_COOKIE, CurrentUser, DbSession
from app.core.security import InvalidTokenError, decode_session_token
from app.models import (
    CardLearnedSelection,
    CardSeedSelection,
    ErpCodeCatalog,
    OrgUnit,
    UserCodeFavorite,
)
from app.services.code_sync import dept_matches_budget_name, sync_catalog
from app.services.cost_project import resolve_cost_project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/me", tags=["me-codes"])

# 카탈로그/동기화 kind — ERP 코드만(에이전트는 카탈로그·동기화 대상이 아님).
_VALID_KINDS = ("budget_unit", "project", "partner", "org_unit")
# 즐겨찾기 kind — 스키마 레벨에서 강제(무효 kind 행 축적 방지, 리뷰 MEDIUM #4).
# 'agent' = 홈 '자주쓰는 에이전트'(code=에이전트 id, name=에이전트명) — 즐겨찾기 전용.
CodeKind = Literal["budget_unit", "project", "partner", "agent"]

# 백그라운드 동기화 태스크 강참조 — 무참조 태스크는 GC 대상이라(파이썬 asyncio 규약) 실행 중
# 소멸하면 브라우저 누수 + 세마포어 미반납으로 영구 409 가 될 수 있다(리뷰 MEDIUM #2).
_SYNC_TASKS: set[asyncio.Task] = set()


# ── 스키마 ────────────────────────────────────────────────────────────────────
class FavoriteCreate(BaseModel):
    kind: CodeKind
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    extra: dict | None = None


class ReorderIn(BaseModel):
    kind: CodeKind
    orderedIds: list[str]


class SyncIn(BaseModel):
    kind: str = Field(min_length=1, max_length=16)


def _fav_dict(f: UserCodeFavorite) -> dict:
    return {
        "id": str(f.id),
        "kind": f.kind,
        "code": f.code,
        "name": f.name,
        "extra": f.extra,
        "sortOrder": f.sort_order,
        "isDefault": f.is_default,
    }


# ── 즐겨찾기 CRUD ─────────────────────────────────────────────────────────────
@router.get("/favorites")
async def list_favorites(user: CurrentUser, db: DbSession, kind: str | None = None) -> dict:
    """현재 유저의 즐겨찾기(순서대로). kind 로 필터."""
    stmt = select(UserCodeFavorite).where(UserCodeFavorite.user_id == user.id)
    if kind:
        stmt = stmt.where(UserCodeFavorite.kind == kind)
    stmt = stmt.order_by(UserCodeFavorite.sort_order.asc(), UserCodeFavorite.created_at.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_fav_dict(f) for f in rows]}


@router.post("/favorites", status_code=status.HTTP_201_CREATED)
async def create_favorite(body: FavoriteCreate, user: CurrentUser, db: DbSession):
    """즐겨찾기 추가. 이미 있는 (user,kind,code)면 기존 행을 200 으로 반환(멱등)."""
    existing = (
        await db.execute(
            select(UserCodeFavorite).where(
                UserCodeFavorite.user_id == user.id,
                UserCodeFavorite.kind == body.kind,
                UserCodeFavorite.code == body.code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return JSONResponse(_fav_dict(existing), status_code=status.HTTP_200_OK)
    max_order = (
        await db.execute(
            select(func.max(UserCodeFavorite.sort_order)).where(
                UserCodeFavorite.user_id == user.id, UserCodeFavorite.kind == body.kind
            )
        )
    ).scalar()
    fav = UserCodeFavorite(
        user_id=user.id,
        kind=body.kind,
        code=body.code,
        name=body.name,
        extra=body.extra,
        sort_order=(max_order or 0) + 1,
    )
    db.add(fav)
    await db.commit()
    return _fav_dict(fav)


@router.delete("/favorites/{fav_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_favorite(fav_id: str, user: CurrentUser, db: DbSession):
    """소유자 스코프 삭제. 대상이 없거나 소유자 불일치면 404."""
    try:
        parsed = uuid.UUID(fav_id)
    except ValueError:
        return JSONResponse({"error": "즐겨찾기를 찾을 수 없습니다."}, status_code=404)
    fav = (
        await db.execute(
            select(UserCodeFavorite).where(
                UserCodeFavorite.id == parsed, UserCodeFavorite.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if fav is None:
        return JSONResponse({"error": "즐겨찾기를 찾을 수 없습니다."}, status_code=404)
    await db.delete(fav)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/favorites/reorder")
async def reorder_favorites(body: ReorderIn, user: CurrentUser, db: DbSession) -> dict:
    """즐겨찾기 순서변경(현재 유저 + kind 스코프). 부분/stale 목록이어도 전체 순열 재구성(간극 없음)."""
    rows = (
        (
            await db.execute(
                select(UserCodeFavorite)
                .where(UserCodeFavorite.user_id == user.id, UserCodeFavorite.kind == body.kind)
                .order_by(UserCodeFavorite.sort_order.asc(), UserCodeFavorite.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    by_id = {str(f.id): f for f in rows}
    ordered: list[str] = []
    for fid in body.orderedIds:  # 클라가 준 순서 중 실재하는 것만, 중복 제거.
        if fid in by_id and fid not in ordered:
            ordered.append(fid)
    for f in rows:  # 목록에 빠진 나머지는 현재 순서대로 뒤에 붙인다.
        if str(f.id) not in ordered:
            ordered.append(str(f.id))
    for index, fid in enumerate(ordered):
        by_id[fid].sort_order = index
    await db.commit()
    return await list_favorites(user, db, kind=body.kind)


@router.post("/favorites/{fav_id}/default")
async def set_default_favorite(fav_id: str, user: CurrentUser, db: DbSession):
    """대상 즐겨찾기의 '기본'을 **토글** — 지정 시 같은 kind 의 기존 default 해제(단일성),
    이미 기본이면 해제(사용자 요청 2026-07-04: 다시 클릭하면 해제).

    소유자 스코프. 대상이 없거나 소유자 불일치면 404. 갱신된 항목을 반환.
    """
    try:
        parsed = uuid.UUID(fav_id)
    except ValueError:
        return JSONResponse({"error": "즐겨찾기를 찾을 수 없습니다."}, status_code=404)
    target = (
        await db.execute(
            select(UserCodeFavorite).where(
                UserCodeFavorite.id == parsed, UserCodeFavorite.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if target is None:
        return JSONResponse({"error": "즐겨찾기를 찾을 수 없습니다."}, status_code=404)
    if target.is_default:
        # 토글 해제 — 그 kind 의 기본 없음 상태가 된다(에이전트는 비용구분 기본 등 폴백 사용).
        target.is_default = False
        await db.commit()
        return _fav_dict(target)
    # 같은 (user,kind) 의 기존 default 를 모두 해제한 뒤 대상만 true — 한 kind 당 1개만 유지.
    siblings = (
        (
            await db.execute(
                select(UserCodeFavorite).where(
                    UserCodeFavorite.user_id == user.id,
                    UserCodeFavorite.kind == target.kind,
                    UserCodeFavorite.is_default.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for s in siblings:
        s.is_default = False
    target.is_default = True
    await db.commit()
    return _fav_dict(target)


# ── 개입 학습(디버그 조회) ───────────────────────────────────────────────────────
@router.get("/card-learning")
async def list_card_learning(user: CurrentUser, db: DbSession) -> dict:
    """현재 사용자의 카드 개입 학습(가맹점→확정 선택) 목록 — 개발 디버그용(빈도·최근순).

    제작 중 'AI 가 무엇을 근거로 추천하는지' 확인용. 본인 데이터만 조회한다.
    """
    rows = (
        (
            await db.execute(
                select(CardLearnedSelection)
                .where(CardLearnedSelection.user_id == user.id)
                .order_by(
                    CardLearnedSelection.count.desc(),
                    CardLearnedSelection.last_used_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "merchant": r.merchant,
                "normMerchant": r.norm_merchant,
                "budget": r.budget,
                "project": r.project,
                "note": r.note,
                "count": r.count,
                "lastUsedAt": r.last_used_at.isoformat() if r.last_used_at else None,
            }
            for r in rows
        ]
    }


@router.delete("/card-learning", status_code=status.HTTP_200_OK)
async def clear_card_learning(user: CurrentUser, db: DbSession) -> dict:
    """현재 사용자의 개입 학습 전체 삭제 — 개발 디버그용. 본인 데이터만. 반환 {deleted:n}."""
    res = await db.execute(
        delete(CardLearnedSelection).where(CardLearnedSelection.user_id == user.id)
    )
    await db.commit()
    return {"deleted": int(res.rowcount or 0)}


@router.delete("/card-learning/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card_learning(item_id: str, user: CurrentUser, db: DbSession):
    """개입 학습 1건 삭제(소유자 스코프) — 대상 없거나 소유자 불일치면 404."""
    try:
        parsed = uuid.UUID(item_id)
    except ValueError:
        return JSONResponse({"error": "학습 항목을 찾을 수 없습니다."}, status_code=404)
    row = (
        await db.execute(
            select(CardLearnedSelection).where(
                CardLearnedSelection.id == parsed, CardLearnedSelection.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return JSONResponse({"error": "학습 항목을 찾을 수 없습니다."}, status_code=404)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/card-learning/seed")
async def list_card_seed(
    user: CurrentUser, db: DbSession, q: str | None = None, limit: int = 50, offset: int = 0
) -> dict:
    """전사 기초자료(seed, 가맹점→계정·적요) 목록 — 개발 디버그용. 공용 데이터(user 무관).

    개인 학습이 없을 때 AI 힌트·폴백으로 쓰는 전사 관례. q 로 가맹점 검색, 빈도순 페이지네이션
    (limit/offset). total 은 **필터 적용 후** 전체 건수라 프론트가 페이지 수를 계산한다. 동빈도
    타이는 norm_merchant 로 안정 정렬(페이지 간 순서 흔들림 방지).
    """
    base = select(CardSeedSelection)
    count_stmt = select(func.count()).select_from(CardSeedSelection)
    if q and q.strip():
        cond = CardSeedSelection.merchant.ilike(f"%{q.strip()}%")
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)
    total = (await db.execute(count_stmt)).scalar() or 0
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    rows = (
        await db.execute(
            base.order_by(CardSeedSelection.count.desc(), CardSeedSelection.norm_merchant)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": str(r.id),
                "merchant": r.merchant,
                "normMerchant": r.norm_merchant,
                "acctCode": r.acct_code,
                "acctName": r.acct_name,
                "note": r.note,
                "count": r.count,
                "dominance": r.dominance,
                "lastYear": r.last_year,
            }
            for r in rows
        ],
    }


# ── 코드 카탈로그 조회 ──────────────────────────────────────────────────────────
@router.get("/trip-defaults")
async def get_trip_defaults(user: CurrentUser, db: DbSession) -> dict:
    """출장 실행 전 폼 기본값 — 소속 팀 비용구분(판/제)에 맞춘 기본 프로젝트 + 부서.

    조직 설정(팀 cost_type)과 프로젝트 기본값을 일치시킨다: 제조원가→PJT_NO 500 / 판관비→800.
    카드 자동화(collect 노드)와 동일 규칙(app.services.cost_project). 팀 미지정·구분 없음·
    카탈로그 미존재면 defaultProject=null(프론트가 기본지정 즐겨찾기로 폴백).
    """
    cost_type: str | None = None
    if user.org_unit_id:
        team = await db.get(OrgUnit, user.org_unit_id)
        if team is not None:
            cost_type = team.cost_type
    project = await resolve_cost_project(cost_type)
    return {"costType": cost_type, "department": user.department, "defaultProject": project}


@router.get("/catalog")
async def get_catalog(
    user: CurrentUser,
    db: DbSession,
    kind: str,
    q: str | None = None,
    dept: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """공용 코드 카탈로그 조회. kind 필수. q=name/code 검색, 페이지네이션.

    예산단위의 '내 부서' 필터는 dept 컬럼이 아니라 **예산단위명 ↔ 부서명 정규화 매칭**
    (dept_matches_budget_name: '인사/기획팀' ↔ '인사기획팀')이다 — ERP 예산단위 목록은 전사
    공통이고 이름이 곧 부서라서다. dept 파라미터: 없음=내 부서 매칭(부서 없으면 전체),
    'all'=전체, 그 외 값=그 부서명으로 매칭.
    """
    if kind not in _VALID_KINDS:
        return JSONResponse({"error": f"알 수 없는 kind: {kind}"}, status_code=422)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    # 두 kind 모두 조합/부가 필드 검색이 필요해 파이썬 필터(행 수천 건 이내라 충분).
    # 예산단위=사업계획·예산계정, 프로젝트=WBS요소명·위치·프로젝트번호까지 커버한다.
    rows = (
        (
            await db.execute(
                select(ErpCodeCatalog)
                .where(ErpCodeCatalog.kind == kind)
                .order_by(ErpCodeCatalog.name.asc(), ErpCodeCatalog.code.asc())
            )
        )
        .scalars()
        .all()
    )

    if kind == "budget_unit":
        # '내 부서' 필터 — 예산단위명 정규화 매칭.
        if dept != "all":
            match_dept = dept or user.department
            if match_dept:
                rows = [r for r in rows if dept_matches_budget_name(match_dept, r.name)]
        # q — 예산단위명·사업계획명·예산계정명·코드 전체에서 부분 매칭.
        if q:
            ql = q.strip().lower()
            rows = [
                r
                for r in rows
                if ql in r.name.lower()
                or ql in r.code.lower()
                or ql in str((r.extra or {}).get("bizplanNm", "")).lower()
                or ql in str((r.extra or {}).get("bgacctNm", "")).lower()
            ]
    elif kind == "project" and q:
        # 프로젝트 — 프로젝트명(name)·코드 + WBS요소명·위치·프로젝트번호(extra)까지 부분 매칭.
        ql = q.strip().lower()
        rows = [
            r
            for r in rows
            if ql in r.name.lower()
            or ql in r.code.lower()
            or ql in str((r.extra or {}).get("wbsNm", "")).lower()
            or ql in str((r.extra or {}).get("loc", "")).lower()
            or ql in str((r.extra or {}).get("pjtNo", "")).lower()
        ]
    elif kind == "partner" and q:
        # 거래처 — 거래처명(name)·코드 + 사업자번호(extra)까지 부분 매칭. 정렬은 기본 이름순.
        ql = q.strip().lower()
        rows = [
            r
            for r in rows
            if ql in r.name.lower()
            or ql in r.code.lower()
            or ql in str((r.extra or {}).get("bizNo", "")).lower()
        ]

    if kind == "project":
        # 프로젝트는 프로젝트번호(→WBS요소 번호) 순으로 정렬(이름순 아님 — 사용자 지정).
        rows = sorted(
            rows,
            key=lambda r: (
                str((r.extra or {}).get("pjtNo", "")),
                str((r.extra or {}).get("wbsNo", "")),
            ),
        )

    total = len(rows)
    page_rows = rows[offset : offset + limit]

    # syncedAt 은 q/필터 무관하게 kind 전체의 최신 동기화 시각.
    synced_at = (
        await db.execute(
            select(func.max(ErpCodeCatalog.synced_at)).where(ErpCodeCatalog.kind == kind)
        )
    ).scalar()
    items = [{"code": r.code, "name": r.name, "extra": r.extra} for r in page_rows]
    return {
        "items": items,
        "total": total,
        "syncedAt": synced_at.isoformat() if synced_at else None,
    }


# ── 헤드리스 동기화 트리거/상태 ─────────────────────────────────────────────────
def _omnisol_password(request: Request) -> str | None:
    """세션 쿠키 JWT 의 jti 로 CredCache 에서 옴니솔 비밀번호 조회(runs.py 와 동일 규약)."""
    cache = getattr(request.app.state, "cred_cache", None)
    if cache is None:
        return None
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        jti = decode_session_token(token).get("jti")
    except InvalidTokenError:
        return None
    if not jti:
        return None
    entry = cache.get(jti)
    return entry.get("p") if entry else None


async def _run_catalog_sync(
    kind: str,
    userid: str,
    password: str,
    browser_factory,
    sessionmaker,
    semaphore: asyncio.Semaphore,
    sync_state: dict,
    run_semaphore: asyncio.Semaphore | None,
) -> None:
    """백그라운드 동기화 — 세마포어 반납 + 결과/에러를 sync_state[kind] 에 기록.

    실 ERP 세션을 여는 작업이므로 전역 ERP 동시실행 예산(run_semaphore)도 함께 점유한다
    — 동기화가 일반 실행 상한(max_concurrent_erp_runs)을 우회하지 않게(리뷰 MEDIUM #1).
    """
    try:
        async with run_semaphore if run_semaphore is not None else nullcontext():
            result = await sync_catalog(kind, userid, password, browser_factory, sessionmaker)
        sync_state[kind] = {
            "running": False,
            "lastSyncedAt": result["syncedAt"],
            "count": result["count"],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — 백그라운드 실패를 상태로 남긴다
        logger.exception("코드 카탈로그 동기화 실패(kind=%s)", kind)
        sync_state[kind] = {
            "running": False,
            "lastSyncedAt": None,
            "count": None,
            "error": str(exc),
        }
    finally:
        semaphore.release()


@router.post("/catalog/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(body: SyncIn, request: Request, user: CurrentUser):
    """카탈로그 동기화 트리거. 1슬롯 세마포어(진행 중이면 409). 백그라운드 실행 → 202."""
    if body.kind not in _VALID_KINDS:
        return JSONResponse({"error": f"알 수 없는 kind: {body.kind}"}, status_code=422)
    password = _omnisol_password(request)
    if not password:
        return JSONResponse(
            {"error": "세션에 자격증명이 없습니다. 다시 로그인해 주세요."}, status_code=409
        )
    semaphore = request.app.state.catalog_sync_semaphore
    if semaphore.locked():
        return JSONResponse({"error": "동기화가 이미 진행 중입니다."}, status_code=409)
    await semaphore.acquire()

    sync_state = request.app.state.catalog_sync_state
    sync_state[body.kind] = {"running": True, "lastSyncedAt": None, "count": None, "error": None}
    browser_factory = getattr(request.app.state, "browser_factory", None)
    sessionmaker = appdb.get_sessionmaker()
    task = asyncio.create_task(
        _run_catalog_sync(
            body.kind,
            user.omnisol_userid,
            password,
            browser_factory,
            sessionmaker,
            semaphore,
            sync_state,
            getattr(request.app.state, "run_semaphore", None),
        )
    )
    _SYNC_TASKS.add(task)
    task.add_done_callback(_SYNC_TASKS.discard)
    return {"started": True}


@router.get("/catalog/sync-status")
async def sync_status(request: Request, user: CurrentUser, db: DbSession, kind: str) -> dict:
    """동기화 상태(진행/마지막 결과) + DB 상의 syncedAt/count(kind 전체 — 카탈로그는 전사 공용)."""
    if kind not in _VALID_KINDS:
        return JSONResponse({"error": f"알 수 없는 kind: {kind}"}, status_code=422)
    sync_state = getattr(request.app.state, "catalog_sync_state", {})
    base = dict(sync_state.get(kind) or {"running": False})
    conds = [ErpCodeCatalog.kind == kind]
    synced_at = (
        await db.execute(select(func.max(ErpCodeCatalog.synced_at)).where(*conds))
    ).scalar()
    count = (
        await db.execute(select(func.count()).select_from(ErpCodeCatalog).where(*conds))
    ).scalar() or 0
    base["syncedAt"] = synced_at.isoformat() if synced_at else None
    base["count"] = count
    return base
