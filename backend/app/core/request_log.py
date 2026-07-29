"""인바운드 HTTP 요청 로깅 미들웨어 — 메서드·경로·상태·소요시간·요청 본문(마스킹).

⚠ 응답 본문은 **절대 읽지 않는다**. 이 앱에는 SSE 엔드포인트가 둘 있고(routers/runs.py 라이브
  실행, routers/assistant.py 어시스턴트 채팅) StreamingResponse 의 body_iterator 를 미들웨어에서
  소비하면 스트림이 버퍼링돼 라이브 화면이 멈춘다. 성공/실패 판정에는 status_code 로 충분하다.

요청 본문 읽기는 안전하다 — Starlette 0.41.3 의 BaseHTTPMiddleware 는 요청을 _CachedRequest 로
감싸므로, dispatch 에서 소비한 본문이 캐시되어 다운스트림 라우터에 그대로 재생된다
(starlette/middleware/base.py 의 _CachedRequest docstring).

레벨은 결과에 맞춘다 — 5xx=error / 4xx=warning / 그 외=info. 실패만 골라 보기 위함이다.
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.redact import body_preview

logger = logging.getLogger("app.http.in")

# 본문이 있을 수 있는 메서드만 읽는다(GET/HEAD 는 읽어봐야 빈 바이트).
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _level_for(status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO


class HttpRequestLogMiddleware(BaseHTTPMiddleware):
    """모든 인바운드 요청을 한 줄로 남긴다."""

    async def dispatch(self, request: Request, call_next) -> Response:
        raw = b""
        if request.method in _BODY_METHODS:
            try:
                raw = await request.body()
            except Exception:  # noqa: BLE001 — 로깅이 요청 처리를 막아선 안 된다.
                raw = b""
        preview = body_preview(raw)
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            # 미처리 예외 = 실패. 스택과 함께 요청 내용을 남겨야 재현이 가능하다.
            logger.exception(
                "%s %s → 예외 (%.0fms) body=%s", request.method, path, elapsed, preview
            )
            raise

        elapsed = (time.perf_counter() - started) * 1000
        logger.log(
            _level_for(response.status_code),
            "%s %s → %d (%.0fms) body=%s",
            request.method,
            path,
            response.status_code,
            elapsed,
            preview,
        )
        return response
