"""LLM 전체 프롬프트·응답 캡처 — 디버깅/감사용(기본 OFF, env 게이트).

settings.llm_prompt_capture(env LLM_PROMPT_CAPTURE)가 켜졌을 때만, 프로바이더가 실제로
전송하는 **와이어 요청 바디**와 그에 대한 **응답 바디**를 JSONL 로 append 한다. 요청·응답은
같은 seq(상관 id)로 짝지어 기록된다 — 동시 호출이 파일에서 섞여도 seq 로 매칭할 수 있다.

- 요청·응답이 곧 "LLM 에 보내는 전체 프롬프트 / LLM 이 돌려준 응답"의 ground truth 다.
- 경로: settings.llm_prompt_capture_path(기본 backend/prompt-capture.jsonl).
- 완전 best-effort: 어떤 예외도 삼켜 LLM 호출/런을 절대 방해하지 않는다.
- 민감정보 주의: 캡처 파일에는 프롬프트·응답 원문(가맹점·금액 등)이 그대로 남는다 —
  디버깅 용도로만 켜고, 수집 후 파일을 정리한다(git 커밋 금지 대상).
"""

from __future__ import annotations

import itertools
import json
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "prompt-capture.jsonl"
_seq_counter = itertools.count(1)


def _enabled_path() -> Path | None:
    """캡처가 켜져 있으면 대상 경로, 아니면 None."""
    settings = get_settings()
    if not getattr(settings, "llm_prompt_capture", False):
        return None
    return Path(getattr(settings, "llm_prompt_capture_path", "") or _DEFAULT_PATH)


def _write(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def capture_request(provider: str, url: str, body: dict) -> int | None:
    """요청 바디 전체를 append 하고 상관 seq 를 반환(응답 캡처에 전달). 꺼져 있으면 None."""
    try:
        path = _enabled_path()
        if path is None:
            return None
        seq = next(_seq_counter)
        _write(path, {"kind": "request", "seq": seq, "provider": provider, "url": url, "body": body})
        return seq
    except Exception:  # noqa: BLE001 — 캡처 실패가 LLM 호출을 막아선 안 된다.
        logger.debug("프롬프트 요청 캡처 실패(무시)", exc_info=True)
        return None


def capture_response(provider: str, url: str, seq: int | None, response: Any) -> None:
    """응답 바디를 같은 seq 로 append. seq 가 None(요청 미캡처)이면 아무것도 안 한다."""
    if seq is None:
        return
    try:
        path = _enabled_path()
        if path is None:
            return
        _write(
            path,
            {"kind": "response", "seq": seq, "provider": provider, "url": url, "response": response},
        )
    except Exception:  # noqa: BLE001 — 캡처 실패가 LLM 응답 처리를 막아선 안 된다.
        logger.debug("프롬프트 응답 캡처 실패(무시)", exc_info=True)
