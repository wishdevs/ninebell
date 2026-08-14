"""변경사항(릴리스 노트) 라우터 — 릴리스 단위 변경 기록 CRUD.

- GET    /changelog            : 목록(최신순 페이지). 로그인 전원. 일반 사용자는 released 만.
- GET    /changelog/{id}       : 단건 조회(딥링크). 일반 사용자는 released 만.
- POST   /changelog            : 등록(관리자). Claude Code 가 커밋 후 호출하는 주 경로.
- PATCH  /changelog/{id}       : 전체 교체 수정(관리자).
- DELETE /changelog/{id}       : 삭제(관리자).

status='draft' 는 관리자 전용(작성 중), 'released' 만 전 사용자에게 공개된다.
version 은 중복 불가 — 충돌 시 409. 응답은 프론트 규약대로 camelCase.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.deps import CurrentUser, DbSession, RequireAdmin
from app.core.listing import PageQuery, paginate
from app.core.permissions import ROLE_ADMIN, role_rank
from app.models import ChangelogEntry, User

router = APIRouter(prefix="/changelog", tags=["changelog"])

ChangelogStatus = Literal["draft", "released"]

# 릴리스 날짜 기본값의 기준 시간대 — 서버가 UTC(ECS)든 KST(로컬)든 같은 '오늘'을 쓴다.
KST = timezone(timedelta(hours=9))


class ChangelogIn(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    body_md: str = Field(min_length=1, alias="bodyMd")
    status: ChangelogStatus = "released"
    # 달력 날짜("2026-07-28"). 생략 시 KST 기준 오늘.
    released_at: date | None = Field(default=None, alias="releasedAt")
    # 잘못 저장·미저장·실행 불가·개인정보 수정 포함 여부 — 목록 배지·필터의 단일 소스.
    has_major_fix: bool = Field(default=False, alias="hasMajorFix")

    model_config = {"populate_by_name": True}


def _entry_dict(e: ChangelogEntry) -> dict:
    return {
        "id": str(e.id),
        "version": e.version,
        "title": e.title,
        "bodyMd": e.body_md,
        "status": e.status,
        "hasMajorFix": e.has_major_fix,
        # 'yyyy-mm-dd' — 달력 날짜라 시각·오프셋을 붙이지 않는다(시간대 밀림 방지).
        "releasedAt": e.released_at.isoformat() if e.released_at else None,
        "createdAt": e.created_at.isoformat() if e.created_at else None,
        "updatedAt": e.updated_at.isoformat() if e.updated_at else None,
    }


def _is_admin(user: User) -> bool:
    return role_rank(user.role.code if user.role is not None else None) >= role_rank(ROLE_ADMIN)


async def _get_or_404(db: DbSession, entry_id: str) -> ChangelogEntry:
    try:
        parsed = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="항목을 찾을 수 없습니다.")
    entry = (
        await db.execute(select(ChangelogEntry).where(ChangelogEntry.id == parsed))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="항목을 찾을 수 없습니다.")
    return entry


async def _assert_version_free(db: DbSession, version: str, exclude_id: uuid.UUID | None) -> None:
    stmt = select(ChangelogEntry.id).where(ChangelogEntry.version == version)
    if exclude_id is not None:
        stmt = stmt.where(ChangelogEntry.id != exclude_id)
    if (await db.execute(stmt)).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"이미 등록된 버전입니다: {version}"
        )


@router.get("")
async def list_changelog(
    user: CurrentUser,
    db: DbSession,
    page: PageQuery,
    q: str | None = Query(default=None),
    status_filter: ChangelogStatus | Literal["all"] = Query(default="all", alias="status"),
    has_major_fix: bool | None = Query(default=None, alias="hasMajorFix"),
) -> dict:
    """최신 릴리스순 목록. 일반 사용자는 status 파라미터와 무관하게 released 만 본다."""
    stmt = select(ChangelogEntry).order_by(
        ChangelogEntry.released_at.desc(), ChangelogEntry.created_at.desc()
    )
    if not _is_admin(user):
        stmt = stmt.where(ChangelogEntry.status == "released")
    elif status_filter != "all":
        stmt = stmt.where(ChangelogEntry.status == status_filter)

    if has_major_fix is not None:
        stmt = stmt.where(ChangelogEntry.has_major_fix.is_(has_major_fix))

    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ChangelogEntry.version.ilike(like),
                ChangelogEntry.title.ilike(like),
                ChangelogEntry.body_md.ilike(like),
            )
        )

    result = await paginate(db, stmt, page)
    return {
        "items": [_entry_dict(e) for e in result.items],
        "total": result.total,
        "limit": result.limit,
        "offset": result.offset,
    }


@router.get("/{entry_id}")
async def get_changelog(entry_id: str, user: CurrentUser, db: DbSession) -> dict:
    entry = await _get_or_404(db, entry_id)
    # 미공개(draft)는 관리자에게만 — 일반 사용자에게는 존재 자체를 숨긴다.
    if entry.status != "released" and not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="항목을 찾을 수 없습니다.")
    return _entry_dict(entry)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_changelog(body: ChangelogIn, _admin: RequireAdmin, db: DbSession) -> dict:
    version = body.version.strip()
    await _assert_version_free(db, version, exclude_id=None)
    entry = ChangelogEntry(
        version=version,
        title=body.title.strip(),
        body_md=body.body_md,
        status=body.status,
        has_major_fix=body.has_major_fix,
        released_at=body.released_at or datetime.now(KST).date(),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _entry_dict(entry)


@router.patch("/{entry_id}")
async def update_changelog(
    entry_id: str, body: ChangelogIn, _admin: RequireAdmin, db: DbSession
) -> dict:
    entry = await _get_or_404(db, entry_id)
    version = body.version.strip()
    await _assert_version_free(db, version, exclude_id=entry.id)
    entry.version = version
    entry.title = body.title.strip()
    entry.body_md = body.body_md
    entry.status = body.status
    entry.has_major_fix = body.has_major_fix
    if body.released_at is not None:
        entry.released_at = body.released_at
    await db.commit()
    await db.refresh(entry)
    return _entry_dict(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_changelog(entry_id: str, _admin: RequireAdmin, db: DbSession) -> Response:
    entry = await _get_or_404(db, entry_id)
    await db.delete(entry)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
