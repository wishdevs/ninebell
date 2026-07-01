"""인증 라우터 — /auth/login, /auth/logout, /auth/me.

로그인 = 더존 옴니솔 헤드리스 검증(authenticate). 성공 시 users upsert + access_log(success)
+ 롤 부여(최초 생성 시 SUPER_ADMIN_OMNISOL_IDS 면 super_admin, 아니면 user) + JWT 세션 쿠키 발급
+ id/pw 를 CredCache 에 jti 키로 보관. 실패 시 access_log(failed) + 401. 비밀번호 DB 저장 금지.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.erp.login as erp_login
from app.config import get_settings
from app.core.deps import (
    SESSION_COOKIE,
    CurrentUser,
    DbSession,
    collect_user_permissions,
    get_role_by_code,
)
from app.core.permissions import ROLE_SUPER_ADMIN, ROLE_USER
from app.core.security import InvalidTokenError, create_session_token, decode_session_token
from app.erp.login import ErpAuthError
from app.models import User
from app.schemas.auth import AuthMe, LoginBody
from app.services.access_log import record_access

logger = logging.getLogger("app.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


async def _upsert_user(db: AsyncSession, userid: str, profile: dict, settings) -> User:
    """더존 검증 성공 후 사용자 upsert. 최초 생성 시 롤 부여."""
    user = (await db.execute(select(User).where(User.omnisol_userid == userid))).scalar_one_or_none()
    if user is None:
        code = ROLE_SUPER_ADMIN if userid in settings.super_admin_id_set() else ROLE_USER
        role = await get_role_by_code(db, code)
        user = User(
            omnisol_userid=userid,
            display_name=(profile.get("display_name") or None),
            department=(profile.get("department") or None),
            email=profile.get("email"),
            status="active",
            role_id=role.id if role is not None else None,
        )
        db.add(user)
        await db.flush()
        return user

    # 기존 사용자 — 프로필 best-effort 갱신(빈 값은 덮어쓰지 않음).
    if profile.get("display_name"):
        user.display_name = profile["display_name"]
    if profile.get("department"):
        user.department = profile["department"]
    if profile.get("email"):
        user.email = profile["email"]
    return user


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, db: DbSession) -> dict:
    settings = get_settings()
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    try:
        async with request.app.state.erp_semaphore:
            profile = await erp_login.authenticate(
                request.app.state.erp_browser, body.userid, body.password, settings.erp_base
            )
    except ErpAuthError as exc:
        await record_access(
            db, omnisol_userid=body.userid, status="failed", error_msg=str(exc), ip=ip, user_agent=ua
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except Exception:  # noqa: BLE001 — 브라우저/네트워크 오류
        logger.exception("login: ERP 헤드리스 로그인 중 오류")
        await record_access(
            db,
            omnisol_userid=body.userid,
            status="failed",
            error_msg="ERP 로그인 중 오류(브라우저/네트워크)",
            ip=ip,
            user_agent=ua,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ERP 로그인 중 오류가 발생했습니다.",
        )

    user = await _upsert_user(db, body.userid, profile, settings)
    user.last_login_at = datetime.now(UTC)
    await record_access(
        db, omnisol_userid=body.userid, status="success", user_id=user.id, ip=ip, user_agent=ua
    )
    await db.commit()

    token, jti = create_session_token(str(user.id))
    request.app.state.cred_cache.put(jti, body.userid, body.password, settings.session_ttl_seconds)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            payload = decode_session_token(token)
            jti = payload.get("jti")
            if jti:
                request.app.state.cred_cache.delete(jti)
        except InvalidTokenError:
            pass
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=AuthMe)
async def me(user: CurrentUser) -> AuthMe:
    return AuthMe(
        id=str(user.id),
        omnisol_userid=user.omnisol_userid,
        display_name=user.display_name,
        department=user.department,
        email=user.email,
        role=user.role.code if user.role is not None else ROLE_USER,
        permissions=sorted(collect_user_permissions(user)),
        last_login_at=user.last_login_at,
    )
