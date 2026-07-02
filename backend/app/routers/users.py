"""사용자(멤버) 라우터 — 목록/롤변경/수정/삭제. admin+ 게이트(권한 코드 기반)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.deps import DbSession, get_role_by_code, require_permission
from app.core.permissions import (
    ROLE_USER,
    USERS_DELETE,
    USERS_READ,
    USERS_WRITE,
    ROLES_ASSIGN,
)
from app.models import OrgUnit, User
from app.schemas.user import RoleUpdate, UserOut, UserPatch

router = APIRouter(prefix="/users", tags=["users"])


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        name=user.display_name or user.omnisol_userid,
        email=user.email or user.omnisol_userid,
        role=user.role.code if user.role is not None else ROLE_USER,
        status=user.status,
        email_verified=user.email is not None,
        last_active_at=user.last_login_at,
        joined_at=user.created_at,
        org_unit_id=user.org_unit_id,
    )


@router.get("", response_model=list[UserOut])
async def list_users(
    db: DbSession,
    _actor: Annotated[User, Depends(require_permission(USERS_READ))],
) -> list[UserOut]:
    rows = (
        (await db.execute(select(User).order_by(User.created_at.asc()))).scalars().all()
    )
    return [_to_user_out(u) for u in rows]


@router.patch("/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: uuid.UUID,
    payload: RoleUpdate,
    db: DbSession,
    _actor: Annotated[User, Depends(require_permission(ROLES_ASSIGN))],
) -> UserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다.")
    role = await get_role_by_code(db, payload.role)
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="알 수 없는 롤입니다.")
    user.role_id = role.id
    await db.commit()
    await db.refresh(user)
    return _to_user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserPatch,
    db: DbSession,
    _actor: Annotated[User, Depends(require_permission(USERS_WRITE))],
) -> UserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다.")
    if payload.status is not None:
        user.status = payload.status
    if "org_unit_id" in payload.model_fields_set:
        # null/"" = 해제, 값 = 존재 검증 후 지정. 멤버는 팀(leaf)에만 배정한다(본부 불가).
        new_org = payload.org_unit_id or None
        if new_org is not None:
            org = await db.get(OrgUnit, new_org)
            if org is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="알 수 없는 조직구분입니다."
                )
            if org.parent_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="본부에는 배정할 수 없습니다. 팀을 선택하세요.",
                )
        user.org_unit_id = new_org
    await db.commit()
    await db.refresh(user)
    return _to_user_out(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_user(
    user_id: uuid.UUID,
    db: DbSession,
    _actor: Annotated[User, Depends(require_permission(USERS_DELETE))],
) -> None:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다.")
    await db.delete(user)
    await db.commit()
