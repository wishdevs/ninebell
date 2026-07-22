"""옴니솔 자격증명 조회 — 세션 쿠키(JWT) jti → CredCache(서버 RAM) 단일 규약.

runs.py(라이브 실행)와 me_codes.py(카탈로그 동기화)에 통째 복붙돼 있던 _omnisol_password 를
단일 소유로 통합. 두 라우터는 `omnisol_password as _omnisol_password` 로 import 한다
(모듈 전역 이름 유지 — 테스트가 라우터 모듈 속성을 monkeypatch 하는 앵커).
"""

from __future__ import annotations

from fastapi import Request

from app.core.deps import SESSION_COOKIE
from app.core.security import InvalidTokenError, decode_session_token


def omnisol_password(request: Request) -> str | None:
    """세션 쿠키 JWT 의 jti 로 CredCache 에서 옴니솔 비밀번호를 조회(없으면 None).

    비밀번호는 로그인 시 서버 RAM(CredCache)에만 jti 키로 보관된다(디스크/DB 미저장).
    실 옴니솔 워크플로우(expense-card-chat)의 로그인 노드가 이 값을 쓴다. demo-echo 는
    비밀번호를 쓰지 않으므로 None 이어도 무해하다. 테스트(lifespan 미실행)에서는 cred_cache
    가 없거나 쿠키가 없어 None 을 반환한다.
    """
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
