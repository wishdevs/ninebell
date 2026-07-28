"""애플리케이션 로깅 부트스트랩 — uvicorn 이 비워두는 root 핸들러를 채운다.

⚠ 근본원인(2026-07-28 실측): `uvicorn app.main:app` 은 자기 로거(uvicorn·uvicorn.access)만
설정하고 **root 에는 핸들러를 달지 않는다**(uvicorn.config.LOGGING_CONFIG 의 root=None).
그래서 `app.*` 로거의 INFO 는 logging 의 lastResort(WARNING 고정)에 걸려 **한 줄도 출력되지
않았다** — ERP 인증 성공(erp/login.py)·추천 청크 수(card_collect/recommend.py) 같은 기존
logger.info 가 전부 유실 중이었다. WARNING 이상만 우연히 보이던 것이다.

여기서 root 에 stdout 핸들러를 달아 애플리케이션 로그가 실제로 나가게 한다.
  · stdout 인 이유: ECS(CloudWatch)·온프렘 모두 표준출력을 수집한다. 컨테이너 파일은 재기동에
    사라지므로 파일 싱크를 두지 않는다.
  · uvicorn·uvicorn.access 는 propagate=False 라 이 핸들러로 중복 출력되지 않는다.
  · 멱등 — create_app 이 테스트에서 여러 번 불려도 핸들러가 쌓이지 않는다.
"""

from __future__ import annotations

import logging
import sys

# 핸들러 식별자 — 재호출 시 같은 핸들러를 다시 달지 않기 위한 표식.
_HANDLER_NAME = "app-stdout"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s — %(message)s"

# root 에 핸들러가 생기면 그동안 조용하던 서드파티 INFO 도 함께 흘러나온다. httpx 는 요청마다
# "HTTP Request: POST ... 200 OK" 를 찍는데 core/http_client 의 훅이 같은 내용을 더 자세히
# (본문·소요시간 포함) 남기므로 순수 중복이다 — 이 로거만 WARNING 으로 낮춘다.
_QUIET_LOGGERS = ("httpx", "httpcore")


def _resolve_level(level: str | None) -> int:
    """레벨 문자열 → logging 상수. 미지 값은 INFO(부팅을 막지 않는다)."""
    resolved = logging.getLevelName((level or "INFO").strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(level: str | None = "INFO") -> None:
    """root 로거에 stdout 핸들러를 달고 레벨을 맞춘다(멱등)."""
    lv = _resolve_level(level)
    root = logging.getLogger()
    root.setLevel(lv)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(lv, logging.WARNING))

    for existing in root.handlers:
        if getattr(existing, "name", None) == _HANDLER_NAME:
            existing.setLevel(lv)
            return

    handler = logging.StreamHandler(sys.stdout)
    handler.name = _HANDLER_NAME
    handler.setLevel(lv)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
