"""LLM 전체 프롬프트·응답 캡처 — 싱크 두 갈래(로그 상시 / JSONL 파일은 env 게이트).

프로바이더가 실제로 전송하는 **와이어 요청 바디**와 그에 대한 **응답 바디**를 남긴다.
요청·응답은 같은 seq(상관 id)로 짝지어 기록된다 — 동시 호출이 섞여도 seq 로 매칭할 수 있다.

  1. **로그(`app.llm.wire`) — 항상.** 상시 보존 경로. stdout 으로 나가 ECS(CloudWatch)·온프렘
     수집기에 쌓인다. 스크린샷 base64 만 생략하고 프롬프트/응답 텍스트는 전문 그대로다.
  2. **JSONL 파일 — settings.llm_prompt_capture(env LLM_PROMPT_CAPTURE) 가 켜졌을 때만.**
     한 파일에 모아 오프라인 분석할 때 쓰는 디버깅 스위치(컨테이너에선 재기동에 사라진다).

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
# 와이어 전문 전용 로거 — 운영에서 레벨/라우팅을 따로 조절할 수 있게 이름을 분리한다.
wire_logger = logging.getLogger("app.llm.wire")

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


def _elide_images(node: Any) -> Any:
    """스크린샷 base64 만 제거한 사본 — 프롬프트/응답 **텍스트는 손대지 않는다**.

    한 장에 수백 KB~수 MB 라 그대로 로그에 실으면 라인 하나가 로그를 삼킨다. 길이 기준으로
    자르면 정작 남겨야 할 긴 컨텍스트(추천 후보 수백 건)가 잘리므로, 두 프로바이더의 **이미지
    필드만 정확히 지목**한다.
      · gemini  — {"inline_data": {"mime_type": ..., "data": <b64>}}
      · etribe  — {"image_url": {"url": "data:image/jpeg;base64,..."}}
    """
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            key = str(k)
            if (
                key == "data"
                and isinstance(v, str)
                and "mime_type" in node  # gemini inline_data 블록 안의 data 만.
            ):
                out[k] = f"<image base64 생략: {len(v)}자>"
            elif key == "url" and isinstance(v, str) and v.startswith("data:"):
                out[k] = f"<data URI 생략: {len(v)}자>"
            else:
                out[k] = _elide_images(v)
        return out
    if isinstance(node, list):
        return [_elide_images(v) for v in node]
    return node


def _wire(kind: str, seq: int, provider: str, url: str, payload: Any) -> None:
    """LLM 와이어 요청/응답 **전문**을 로그로 남긴다(항상 — env 게이트 없음).

    파일 캡처(_enabled_path)는 디버깅용 스위치라 기본 OFF 이고 컨테이너에서는 재기동에
    사라진다. 상시 보존은 stdout → CloudWatch/온프렘 수집기 경로가 담당한다. request 와
    response 는 같은 seq 로 짝지어지므로 동시 호출이 섞여도 매칭된다.
    """
    try:
        body = json.dumps(_elide_images(payload), ensure_ascii=False)
        wire_logger.info("%s seq=%d provider=%s url=%s %s", kind, seq, provider, url, body)
    except Exception:  # noqa: BLE001 — 로깅 실패가 LLM 호출을 막아선 안 된다.
        logger.debug("LLM 와이어 로깅 실패(무시)", exc_info=True)


def capture_request(provider: str, url: str, body: dict) -> int | None:
    """요청 바디 전체를 로그(항상)와 JSONL(env 게이트)에 남기고 상관 seq 를 반환."""
    seq = next(_seq_counter)
    _wire("request", seq, provider, url, body)
    try:
        path = _enabled_path()
        if path is None:
            return seq
        _write(path, {"kind": "request", "seq": seq, "provider": provider, "url": url, "body": body})
    except Exception:  # noqa: BLE001 — 캡처 실패가 LLM 호출을 막아선 안 된다.
        logger.debug("프롬프트 요청 캡처 실패(무시)", exc_info=True)
    return seq


def capture_response(provider: str, url: str, seq: int | None, response: Any) -> None:
    """응답 바디를 같은 seq 로 남긴다. seq 가 None(요청 미캡처)이면 아무것도 안 한다."""
    if seq is None:
        return
    _wire("response", seq, provider, url, response)
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
