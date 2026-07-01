"""세션 JWT(HS256) 발급/검증 — PyJWT.

DB 의존성이 없어 단위 테스트가 쉽다(ax `core/security.py` 구조 이식, PyJWT 로 교체).
세션 토큰은 httpOnly 쿠키로 운반되며 claim: sub(user.id), jti, iat, exp, type='session'.
옴니솔 계정은 비밀번호를 DB 에 저장하지 않는다(인증 권위는 헤드리스 검증).
단, 로컬 계정(시스템 관리자 등)만 bcrypt 해시를 저장/검증한다(hash_password/verify_password).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import get_settings

_TOKEN_TYPE: str = "session"


class InvalidTokenError(Exception):
    """JWT 서명/형식/만료 검증 실패."""


def create_session_token(subject: str, *, jti: str | None = None, ttl_seconds: int | None = None) -> tuple[str, str]:
    """세션 JWT 를 생성해 ``(token, jti)`` 반환.

    ``jti`` 미지정 시 새 UUID 를 발급한다. 호출자는 jti 로 자격증명 캐시를 키잉한다.
    """
    s = get_settings()
    now = datetime.now(tz=UTC)
    effective_ttl = ttl_seconds if ttl_seconds is not None else s.session_ttl_seconds
    token_jti = jti or uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": subject,
        "jti": token_jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=effective_ttl)).timestamp()),
        "type": _TOKEN_TYPE,
    }
    token = jwt.encode(payload, s.auth_secret, algorithm=s.jwt_algorithm)
    return token, token_jti


def decode_session_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(token, s.auth_secret, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != _TOKEN_TYPE:
        raise InvalidTokenError("not a session token")
    return payload


def hash_password(password: str) -> str:
    """로컬 계정 비밀번호를 bcrypt 로 해싱해 문자열로 반환."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """평문 비밀번호를 bcrypt 해시와 대조. 해시가 손상돼도 예외 없이 False."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
