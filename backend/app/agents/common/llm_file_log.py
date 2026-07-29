"""LLM 호출 1건 = 파일 3개 — 메타데이터(.log) + 요청 페이로드/응답(.json).

`app.llm.wire` 한 줄 로그는 프롬프트가 수천 자라 터미널·app.log 에서 사실상 읽을 수 없다.
여기서는 호출마다 파일을 나눠 남긴다.

    20260729-093336_generateCo_1.log            ← 메타데이터(JSON): 시각·URL·소요시간·크기
    20260729-093336_generateCo_1.request.json   ← 요청 페이로드 전문
    20260729-093336_generateCo_1.response.json  ← 응답 전문

이름 규칙 `YYYYMMDD-HHMMSS_<url10>_<seq>`:
  · `<url10>` — 요청 URL 마지막 경로 조각의 10자. `모델:오퍼레이션` 꼴이면 콜론 뒤만 쓴다
    (`…:generateContent` → `generateCo`, `/v1/chat/completions` → `completion`).
    URL 앞 10자('https://ge')는 모든 호출이 같아 구분에 쓸모가 없다.
  · `<seq>` — 같은 초에 여러 호출이 날아가면(추천은 청크 3개 동시) 이름이 겹치므로 붙인다.
    prompt_capture 의 상관 seq 와 같은 값이라 app.llm.wire 로그와도 짝이 맞는다.

세 파일 모두 **유효한 JSON**이다(`indent=2`, `ensure_ascii=False` — 한글이 그대로 보인다).
jq·에디터로 바로 열어 보거나 스크립트로 파싱할 수 있다.

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

# seq → (파일 이름 앞부분, 메타데이터 dict, 요청 시작 시각). 응답이 오면 메타를 갱신해 다시 쓴다.
_pending: dict[int, tuple[Path, dict, float]] = {}
# 응답이 끝내 안 오는 호출(예외·타임아웃)이 쌓여 메모리를 먹지 않도록 상한을 둔다.
_MAX_PENDING = 256

_URL_SLUG_LEN = 10
_TIME_FMT = "%Y-%m-%d %H:%M:%S.%f"


def _slug(url: str) -> str:
    """URL 에서 파일명에 쓸 10자를 뽑는다 — 호출 종류가 한눈에 보이게.

    마지막 경로 조각을 잡고, gemini 처럼 `모델:오퍼레이션` 꼴이면 콜론 뒤(오퍼레이션)만 남긴다.
    """
    tail = str(url or "").rstrip("/").split("/")[-1].split("?")[0]
    tail = tail.split(":")[-1] or tail  # 'model:operation' → operation.
    cleaned = re.sub(r"[^0-9A-Za-z]+", "", tail) or "llm"
    return cleaned[:_URL_SLUG_LEN]


def _dump(path: Path, payload: Any) -> int:
    """JSON 을 들여쓰기해 쓰고 바이트 수를 반환(메타의 size 필드용)."""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def _resolve_dir() -> Path | None:
    from app.config import get_settings

    raw = (getattr(get_settings(), "llm_log_dir", "") or "").strip()
    return Path(raw).expanduser() if raw else None


def write_request(seq: int, provider: str, url: str, body: Any) -> None:
    """요청 페이로드(.request.json)와 메타데이터(.log)를 쓴다. 미설정이면 무동작."""
    try:
        base_dir = _resolve_dir()
        if base_dir is None:
            return
        base_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        stem = base_dir / f"{now:%Y%m%d-%H%M%S}_{_slug(url)}_{seq}"

        size = _dump(stem.with_suffix(".request.json"), body)
        meta = {
            "seq": seq,
            "provider": provider,
            "url": url,
            "requestedAt": now.strftime(_TIME_FMT),
            "requestBytes": size,
            "requestFile": stem.with_suffix(".request.json").name,
            # 응답이 오면 채워진다. 남아 있으면 그 호출은 응답 없이 끝난 것이다.
            "respondedAt": None,
            "elapsedMs": None,
            "responseBytes": None,
            "responseFile": None,
        }
        _dump(stem.with_suffix(".log"), meta)

        if len(_pending) >= _MAX_PENDING:
            _pending.pop(next(iter(_pending)), None)  # 가장 오래된 미완 호출부터 버린다.
        _pending[seq] = (stem, meta, time.perf_counter())
    except Exception:  # noqa: BLE001 — 로깅 실패가 LLM 호출을 막아선 안 된다.
        logger.debug("LLM 호출 파일(요청) 기록 실패(무시)", exc_info=True)


def write_response(seq: int, provider: str, url: str, response: Any) -> None:
    """응답(.response.json)을 쓰고 메타데이터(.log)를 갱신한다. 요청 기록이 없으면 무동작."""
    try:
        entry = _pending.pop(seq, None)
        if entry is None:
            return
        stem, meta, started = entry
        now = datetime.now()

        size = _dump(stem.with_suffix(".response.json"), response)
        meta.update(
            respondedAt=now.strftime(_TIME_FMT),
            elapsedMs=round((time.perf_counter() - started) * 1000),
            responseBytes=size,
            responseFile=stem.with_suffix(".response.json").name,
        )
        _dump(stem.with_suffix(".log"), meta)
    except Exception:  # noqa: BLE001 — 응답 처리를 막아선 안 된다.
        logger.debug("LLM 호출 파일(응답) 기록 실패(무시)", exc_info=True)
