"""인증/인가 공용 FastAPI 의존성 (ax `core/deps.py` 이식, 쿠키 세션 + 단일 롤로 단순화).

- get_current_user: httpOnly 쿠키 `session`(JWT) → User(롤·권한 eager-load).
- require_permission(code) / require_any_permission(*codes) / require_role_min(rank): 인가 게이트.
- collect_user_permissions(user): 평탄화된 권한 코드 집합.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import role_rank
from app.core.security import InvalidTokenError, decode_session_token
from app.db import get_db
from app.models import Role, User

DbSession = Annotated[AsyncSession, Depends(get_db)]

SESSION_COOKIE = "session"


def collect_user_permissions(user: User) -> set[str]:
    """사용자에게 부여된 권한 코드의 평탄화 집합(단일 롤 → role_permissions)."""
    codes: set[str] = set()
    if user.role is not None:
        for rp in user.role.role_permissions:
            codes.add(rp.permission.code)
    return codes


def user_has_permission(user: User, code: str) -> bool:
    return code in collect_user_permissions(user)


def _unauthorized(detail: str = "인증이 필요합니다.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def get_current_user(request: Request, db: DbSession) -> User:
    """세션 쿠키(JWT)로 현재 사용자를 해석. 미인증/비활성 시 401."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthorized("세션 쿠키가 없습니다.")
    try:
        payload = decode_session_token(token)
    except InvalidTokenError as exc:
        raise _unauthorized("세션이 유효하지 않습니다.") from exc

    # 세션 무효화: jti 가 CredCache 에 없으면(로그아웃/TTL 만료/서버 재시작) 거부한다.
    # JWT 는 무상태라 이 검사 없이는 로그아웃해도 토큰이 살아있다. cred_cache 미존재
    # (테스트/lifespan 미실행)면 스킵 — 런타임엔 lifespan 이 항상 생성한다.
    cache = getattr(request.app.state, "cred_cache", None)
    if cache is not None:
        jti = payload.get("jti")
        if not jti or cache.get(jti) is None:
            raise _unauthorized("세션이 만료되었거나 로그아웃되었습니다.")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise _unauthorized("세션이 유효하지 않습니다.")
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise _unauthorized("세션이 유효하지 않습니다.") from exc

    # User.role / Role.role_permissions / RolePermission.permission 은 lazy="selectin"
    # 이라 단일 조회로 권한까지 eager-load 된다.
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.status != "active":
        raise _unauthorized("세션이 유효하지 않습니다.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(code: str) -> Callable[..., Awaitable[User]]:
    """단일 권한을 강제하는 의존성. 권한 없으면 403."""

    async def _checker(user: CurrentUser) -> User:
        if not user_has_permission(user, code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="권한이 부족합니다.",
            )
        return user

    _checker.__name__ = f"require_permission_{code.replace(':', '_')}"
    return _checker


def require_any_permission(*codes: str) -> Callable[..., Awaitable[User]]:
    """주어진 권한 중 하나라도 있으면 통과(any-of). 없으면 403."""

    async def _checker(user: CurrentUser) -> User:
        granted = collect_user_permissions(user)
        if not any(c in granted for c in codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="권한이 부족합니다.",
            )
        return user

    _checker.__name__ = "require_any_permission_" + "_".join(c.replace(":", "_") for c in codes)
    return _checker


def require_role_min(min_rank: int) -> Callable[..., Awaitable[User]]:
    """계층 최소 롤을 강제(user=1 < admin=2 < super_admin=3). 미만이면 403."""

    async def _checker(user: CurrentUser) -> User:
        code = user.role.code if user.role is not None else None
        if role_rank(code) < min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="권한이 부족합니다.",
            )
        return user

    _checker.__name__ = f"require_role_min_{min_rank}"
    return _checker


async def get_role_by_code(db: AsyncSession, code: str) -> Role | None:
    return (await db.execute(select(Role).where(Role.code == code))).scalar_one_or_none()
