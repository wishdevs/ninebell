"""인증 라우터 — /auth/login, /auth/signup, /auth/logout, /auth/me.

로그인 분기(CONTRACT_V2 A):
- 로컬 계정(users 에 userid 존재 + password_hash NOT NULL, 예: admin) → bcrypt 로컬 검증.
  옴니솔/헤드리스 미호출. 성공 → 세션 발급, 실패 → 401 + access_log(failed).
- 옴니솔 계정 → 헤드리스 authenticate(). 성공 & 유저 존재 → 세션 발급.
  성공 & 유저 없음(첫 접속) → 세션 미발급, pending-signup 캐시에 보관 후
  {signupRequired, signupToken, prefill} 반환. 실패 → 401 + access_log(failed).
회원가입(/auth/signup)이 계정 생성을 담당한다(로그인은 더 이상 자동 생성하지 않음).
옴니솔 비밀번호 DB 저장 금지 — id/pw 는 CredCache 에 jti 키로만 보관.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

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
from app.core.security import (
    InvalidTokenError,
    create_session_token,
    decode_session_token,
    verify_password,
)
from app.erp.login import ErpAuthError
from app.models import User
from app.schemas.auth import AuthMe, LoginBody, SignupBody
from app.services.access_log import record_access

logger = logging.getLogger("app.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_session(
    request: Request, response: Response, *, user_id, userid: str, password: str, settings
) -> None:
    """세션 JWT 쿠키를 발급하고 id/pw 를 CredCache 에 jti 키로 보관."""
    token, jti = create_session_token(str(user_id))
    request.app.state.cred_cache.put(jti, userid, password, settings.session_ttl_seconds)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _apply_profile(user: User, profile: dict) -> None:
    """기존 사용자 프로필 best-effort 갱신(빈 값은 덮어쓰지 않음)."""
    if profile.get("display_name"):
        user.display_name = profile["display_name"]
    if profile.get("department"):
        user.department = profile["department"]
    if profile.get("email"):
        user.email = profile["email"]


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, db: DbSession) -> dict:
    settings = get_settings()
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    user = (
        await db.execute(select(User).where(User.omnisol_userid == body.userid))
    ).scalar_one_or_none()

    # 1) 로컬 계정: bcrypt 로컬 검증(옴니솔 미호출).
    if user is not None and user.password_hash is not None:
        if not verify_password(body.password, user.password_hash):
            await record_access(
                db,
                omnisol_userid=body.userid,
                status="failed",
                error_msg="비밀번호가 올바르지 않습니다.",
                ip=ip,
                user_agent=ua,
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="아이디 또는 비밀번호가 올바르지 않습니다.",
            )
        user.last_login_at = datetime.now(UTC)
        await record_access(
            db, omnisol_userid=body.userid, status="success", user_id=user.id, ip=ip, user_agent=ua
        )
        await db.commit()
        _issue_session(
            request, response, user_id=user.id, userid=body.userid, password=body.password, settings=settings
        )
        return {"ok": True}

    # 2) 옴니솔 계정: 헤드리스 검증.
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

    # 2a) 기존 옴니솔 유저 → 세션 발급(기존 동작).
    if user is not None:
        _apply_profile(user, profile)
        user.last_login_at = datetime.now(UTC)
        await record_access(
            db, omnisol_userid=body.userid, status="success", user_id=user.id, ip=ip, user_agent=ua
        )
        await db.commit()
        _issue_session(
            request, response, user_id=user.id, userid=body.userid, password=body.password, settings=settings
        )
        return {"ok": True}

    # 2b) 첫 접속(유저 없음) → 세션 미발급, 회원가입 유도.
    signup_token = request.app.state.signup_cache.put(
        body.userid,
        body.password,
        profile.get("display_name") or "",
        profile.get("department") or "",
    )
    await record_access(
        db, omnisol_userid=body.userid, status="success", user_id=None, ip=ip, user_agent=ua
    )
    await db.commit()
    return {
        "signupRequired": True,
        "signupToken": signup_token,
        "prefill": {
            "displayName": profile.get("display_name") or "",
            "department": profile.get("department") or "",
        },
    }


@router.post("/signup")
async def signup(body: SignupBody, request: Request, response: Response, db: DbSession) -> dict:
    settings = get_settings()

    pending = request.app.state.signup_cache.get(body.signup_token)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="회원가입 요청이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요.",
        )
    if body.agreed_terms is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="약관에 동의해야 가입할 수 있습니다.",
        )

    userid = pending["userid"]
    password = pending["password"]

    # 중복 가입 방지(경쟁/재제출).
    existing = (
        await db.execute(select(User).where(User.omnisol_userid == userid))
    ).scalar_one_or_none()
    if existing is not None:
        request.app.state.signup_cache.delete(body.signup_token)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 가입된 계정입니다. 다시 로그인해 주세요.",
        )

    code = ROLE_SUPER_ADMIN if userid in settings.super_admin_id_set() else ROLE_USER
    role = await get_role_by_code(db, code)
    now = datetime.now(UTC)
    user = User(
        omnisol_userid=userid,
        display_name=body.display_name or None,
        department=body.department or None,
        email=body.email,
        status="active",
        role_id=role.id if role is not None else None,
        agreed_terms_at=now,
        last_login_at=now,
    )
    db.add(user)
    await db.flush()
    await db.commit()

    _issue_session(
        request, response, user_id=user.id, userid=userid, password=password, settings=settings
    )
    request.app.state.signup_cache.delete(body.signup_token)
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
