"""HTTP 본문 로깅용 민감정보 마스킹 + 길이 절단.

인바운드 미들웨어(core/request_log)와 아웃바운드 훅(core/http_client)이 공유한다.

⚠ 마스킹은 선택이 아니라 필수다 — 로그인 요청 본문에 **평문 비밀번호**가 들어온다
  (schemas/auth.LoginBody.password). 전 요청 본문을 그대로 남기면 로그 파일에 비밀번호가
  그대로 쌓인다.

비 JSON 본문(폼·멀티파트·바이너리)은 **내용을 남기지 않는다** — 키 기반 마스킹이 통하지
않아 무엇이 샐지 보장할 수 없기 때문이다. 이 앱의 실 페이로드는 전부 JSON 이라 손실이 없다.
"""

from __future__ import annotations

import json
from typing import Any

# 값을 통째로 가릴 키(소문자 비교). 부분일치가 아니라 정확일치 — 'passwordHint' 같은 무해한
# 필드까지 가려 디버깅을 방해하지 않으려는 의도.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "current_password",
        "new_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "secret",
        "api_key",
        "apikey",
        "gemini_api_key",
        "auth_secret",
    }
)

MASK = "***"
# 본문 미리보기 상한(자). 카탈로그 업로드 같은 대용량이 로그를 채우지 않게 한다.
MAX_BODY_CHARS = 4_096


def redact_value(value: Any) -> Any:
    """dict/list 를 재귀 순회하며 SENSITIVE_KEYS 의 값을 MASK 로 치환한 **새 객체**를 반환."""
    if isinstance(value, dict):
        return {
            k: (MASK if str(k).lower() in SENSITIVE_KEYS else redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…(+{len(text) - max_chars}자)"


def body_preview(raw: bytes | str | None, *, max_chars: int = MAX_BODY_CHARS) -> str:
    """요청 본문 → 로그용 한 줄. JSON 이면 마스킹 후 절단, 아니면 크기만 남긴다."""
    if not raw:
        return "-"

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary {len(raw)}B>"
    else:
        text = str(raw)

    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        # 폼/멀티파트/평문 — 키 기반 마스킹이 불가능하므로 내용을 남기지 않는다.
        return f"<non-json {len(text)}자>"

    return _truncate(json.dumps(redact_value(parsed), ensure_ascii=False), max_chars)
