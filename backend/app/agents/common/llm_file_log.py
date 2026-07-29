"""LLM 호출 1건 = 파일 1개 — **사람이 읽으려고** 만드는 로그.

`app.llm.wire` 한 줄 로그는 프롬프트가 수천 자라 터미널·app.log 에서 사실상 읽을 수 없다.
여기서는 호출마다 파일을 하나 만들어 요청 URL·요청 바디·응답 바디를 섹션으로 나눠 적는다.

파일명: `YYYYMMDD-HHMMSS_<url10>_<seq>.log`
  · `<url10>` — 요청 URL 의 마지막 경로 조각 10자(`…:generateContent` → `generateCo`,
    `/v1/chat/completions` → `completion`). 앞 10자('https://ge')는 모든 호출이 같아
    구분이 안 되므로 뒤에서 딴다.
  · `<seq>` — 같은 초에 여러 호출이 날아가면(추천은 청크 3개 동시) 파일명이 겹치므로 붙인다.
    prompt_capture 의 상관 seq 와 같은 값이라 app.llm.wire 로그와도 짝이 맞는다.

⚠ 이 파일은 **읽기용**이다. 가독성을 위해 JSON 문자열 안의 `\\n` 을 실제 줄바꿈으로 펴서
  쓰므로 JSON 으로 파싱되지 않는다. 기계가 읽을 원본이 필요하면 LLM_PROMPT_CAPTURE=1 의
  JSONL(prompt_capture) 또는 app.llm.wire 로그를 쓴다.

디렉터리(settings.llm_log_dir)가 비어 있으면 아무것도 하지 않는다 — 배포 기본값. 컨테이너
안 파일은 재기동에 사라지고 stdout 이 이미 수집되므로 로컬 개발용 기능이다.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# seq → (파일 경로, 요청 시작 시각). 응답을 같은 파일에 이어 쓰기 위해 들고 있는다.
_pending: dict[int, tuple[Path, float]] = {}
# 응답이 끝내 안 오는 호출(예외·타임아웃)이 쌓여 메모리를 먹지 않도록 상한을 둔다.
_MAX_PENDING = 256

_URL_SLUG_LEN = 10
_SECTION = "=" * 72


def _slug(url: str) -> str:
    """URL 에서 파일명에 쓸 10자를 뽑는다 — 호출 종류가 한눈에 보이게.

    마지막 경로 조각을 잡고, gemini 처럼 `모델:오퍼레이션` 꼴이면 콜론 뒤(오퍼레이션)만 남긴다.
      · `…/models/gemini-3.6-flash:generateContent` → `generateCo`
      · `…/v1/chat/completions`                     → `completion`
    URL 앞 10자('https://ge')는 모든 호출이 동일해 구분에 쓸모가 없다.
    """
    tail = str(url or "").rstrip("/").split("/")[-1].split("?")[0]
    tail = tail.split(":")[-1] or tail  # 'model:operation' → operation.
    cleaned = re.sub(r"[^0-9A-Za-z]+", "", tail) or "llm"
    return cleaned[:_URL_SLUG_LEN]


def _readable(payload: Any) -> str:
    """들여쓴 JSON + 문자열 안의 개행 복원 — 프롬프트 원문을 눈으로 읽기 위한 형태."""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    # JSON 이스케이프를 실제 문자로 되돌린다(파싱 가능성보다 가독성 우선 — 모듈 docstring 참고).
    return text.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def _resolve_dir() -> Path | None:
    from app.config import get_settings

    raw = (getattr(get_settings(), "llm_log_dir", "") or "").strip()
    return Path(raw).expanduser() if raw else None


def write_request(seq: int, provider: str, url: str, body: Any) -> None:
    """호출 파일을 만들고 요청 섹션을 쓴다. 디렉터리 미설정이면 아무것도 안 한다."""
    try:
        base = _resolve_dir()
        if base is None:
            return
        base.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = base / f"{now:%Y%m%d-%H%M%S}_{_slug(url)}_{seq}.log"
        with path.open("w", encoding="utf-8") as f:
            f.write(f"{_SECTION}\nREQUEST  seq={seq}  provider={provider}\n")
            f.write(f"time : {now:%Y-%m-%d %H:%M:%S.%f}\n")
            f.write(f"url  : {url}\n{_SECTION}\n")
            f.write(_readable(body))
            f.write("\n\n")
        if len(_pending) >= _MAX_PENDING:
            _pending.pop(next(iter(_pending)), None)  # 가장 오래된 미완 호출부터 버린다.
        _pending[seq] = (path, time.perf_counter())
    except Exception:  # noqa: BLE001 — 로깅 실패가 LLM 호출을 막아선 안 된다.
        logger.debug("LLM 호출 파일(요청) 기록 실패(무시)", exc_info=True)


def write_response(seq: int, provider: str, url: str, response: Any) -> None:
    """같은 seq 의 파일에 응답 섹션을 이어 쓴다. 요청 기록이 없으면 건너뛴다."""
    try:
        entry = _pending.pop(seq, None)
        if entry is None:
            return
        path, started = entry
        now = datetime.now()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{_SECTION}\nRESPONSE seq={seq}  provider={provider}\n")
            f.write(f"time : {now:%Y-%m-%d %H:%M:%S.%f}\n")
            f.write(f"took : {(time.perf_counter() - started) * 1000:.0f}ms\n")
            f.write(f"url  : {url}\n{_SECTION}\n")
            f.write(_readable(response))
            f.write("\n")
    except Exception:  # noqa: BLE001 — 응답 처리를 막아선 안 된다.
        logger.debug("LLM 호출 파일(응답) 기록 실패(무시)", exc_info=True)
