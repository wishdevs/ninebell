"""아웃바운드 httpx 클라이언트 팩토리 — 우리가 **보내는** 모든 요청에 로깅 훅을 단다.

FastAPI/Starlette 미들웨어는 **들어오는** 요청만 본다. LLM(gemini·etribe) 처럼 우리가 나가서
호출하는 건 httpx 의 event_hooks 로만 잡힌다. 클라이언트 생성이 여기저기 흩어져 있으면 훅이
빠진 경로가 생기므로 **생성을 이 팩토리 하나로 모은다**.

⚠ 응답 본문은 읽지 않는다 — app.state.http 는 어시스턴트 Gemini **스트리밍**에 쓰인다
  (routers/assistant.py). 훅에서 response.aread() 를 부르면 스트리밍이 깨진다. 여기서는
  메서드·URL·상태·소요시간·요청 본문만 남기고, LLM 요청/응답 **전문**은 별도 경로인
  agents/common/prompt_capture 가 남긴다.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.redact import body_preview

logger = logging.getLogger("app.http.out")

# 요청 시작 시각을 얹어두는 extensions 키(응답 훅에서 소요시간 계산).
_START_KEY = "_app_log_started_at"


def _level_for(status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO


async def _on_request(request: httpx.Request) -> None:
    request.extensions[_START_KEY] = time.perf_counter()


async def _on_response(response: httpx.Response) -> None:
    request = response.request
    started = request.extensions.get(_START_KEY)
    elapsed = (time.perf_counter() - started) * 1000 if started else -1.0
    try:
        raw = request.content
    except Exception:  # noqa: BLE001 — 스트리밍 요청은 content 접근이 막혀 있다.
        raw = b""
    logger.log(
        _level_for(response.status_code),
        "%s %s → %d (%.0fms) body=%s",
        request.method,
        request.url,
        response.status_code,
        elapsed,
        body_preview(raw),
    )


def new_async_client(**kwargs: Any) -> httpx.AsyncClient:
    """로깅 훅이 달린 httpx.AsyncClient. 호출부가 넘긴 event_hooks 는 보존한다."""
    hooks = {k: list(v) for k, v in (kwargs.pop("event_hooks", None) or {}).items()}
    hooks["request"] = [_on_request, *hooks.get("request", [])]
    hooks["response"] = [*hooks.get("response", []), _on_response]
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)
