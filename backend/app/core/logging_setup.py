"""애플리케이션 로깅 부트스트랩 — uvicorn 이 비워두는 root 핸들러를 채운다.

⚠ 근본원인(2026-07-28 실측): `uvicorn app.main:app` 은 자기 로거(uvicorn·uvicorn.access)만
설정하고 **root 에는 핸들러를 달지 않는다**(uvicorn.config.LOGGING_CONFIG 의 root=None).
그래서 `app.*` 로거의 INFO 는 logging 의 lastResort(WARNING 고정)에 걸려 **한 줄도 출력되지
않았다** — ERP 인증 성공(erp/login.py)·추천 청크 수(card_collect/recommend.py) 같은 기존
logger.info 가 전부 유실 중이었다. WARNING 이상만 우연히 보이던 것이다.

싱크는 둘이며 **stdout 은 항상, 파일은 LOG_FILE 이 지정됐을 때만**이다.
  · stdout — 배포 환경의 기본 경로. ECS 는 awslogs 드라이버로 CloudWatch, 온프렘은 Docker
    json-file 로 수집한다. 컨테이너 안 파일은 재기동에 사라지므로 배포에선 파일을 안 쓴다.
  · 파일(LOG_FILE) — 로컬 개발용. 터미널을 닫아도 남기려면 경로를 준다(회전 포함).
    배포에서 굳이 켤 이유는 없지만, 켜도 회전 상한이 있어 디스크를 채우지 않는다.

uvicorn·uvicorn.access 는 propagate=False 라 이 핸들러들로 중복 출력되지 않는다.
멱등 — create_app 이 테스트에서 여러 번 불려도 핸들러가 쌓이지 않는다.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

# 핸들러 식별자 — 재호출 시 같은 핸들러를 다시 달지 않기 위한 표식.
_STDOUT_HANDLER = "app-stdout"
_FILE_HANDLER = "app-file"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s — %(message)s"

# 파일 싱크 회전 — LLM 요청/응답 전문이 호출당 수 KB 라 상한 없이 두면 금방 커진다.
# 50MB × (본체 + 백업 5) = 최대 약 300MB.
_FILE_MAX_BYTES = 50 * 1024 * 1024
_FILE_BACKUP_COUNT = 5

# root 에 핸들러가 생기면 그동안 조용하던 서드파티 INFO 도 함께 흘러나온다. httpx 는 요청마다
# "HTTP Request: POST ... 200 OK" 를 찍는데 core/http_client 의 훅이 같은 내용을 더 자세히
# (본문·소요시간 포함) 남기므로 순수 중복이다 — 이 로거만 WARNING 으로 낮춘다.
_QUIET_LOGGERS = ("httpx", "httpcore")

logger = logging.getLogger(__name__)


def _resolve_level(level: str | None) -> int:
    """레벨 문자열 → logging 상수. 미지 값은 INFO(부팅을 막지 않는다)."""
    resolved = logging.getLevelName((level or "INFO").strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def _find(root: logging.Logger, name: str) -> logging.Handler | None:
    return next((h for h in root.handlers if getattr(h, "name", None) == name), None)


def _attach_file_handler(root: logging.Logger, path_str: str, level: int) -> None:
    """회전 파일 핸들러를 단다. 경로 생성 실패는 경고만 하고 stdout 로깅은 유지한다."""
    try:
        path = Path(path_str).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=_FILE_MAX_BYTES,
            backupCount=_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        # 읽기전용 FS·권한 없음 등 — 로그 파일 하나 때문에 부팅을 막지 않는다.
        logger.warning("로그 파일을 열 수 없어 stdout 만 사용합니다: %s", path_str, exc_info=True)
        return
    handler.name = _FILE_HANDLER
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)


def configure_logging(level: str | None = "INFO", log_file: str | None = None) -> None:
    """root 로거에 stdout(+선택적 파일) 핸들러를 달고 레벨을 맞춘다(멱등).

    log_file 이 비어 있으면 stdout 만 쓴다(배포 기본값).
    """
    lv = _resolve_level(level)
    root = logging.getLogger()
    root.setLevel(lv)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(lv, logging.WARNING))

    stdout_handler = _find(root, _STDOUT_HANDLER)
    if stdout_handler is not None:
        stdout_handler.setLevel(lv)
    else:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.name = _STDOUT_HANDLER
        stdout_handler.setLevel(lv)
        stdout_handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(stdout_handler)

    target = (log_file or "").strip()
    existing_file = _find(root, _FILE_HANDLER)
    if not target:
        return
    if existing_file is not None:
        existing_file.setLevel(lv)
        return
    _attach_file_handler(root, target, lv)
