"""Gemini function-calling 한 턴 — 대화형 에이전트 공용 판단 호출.

ninebell-bak `erp/graph.py` 의 `_gemini_chat_decide` 를 이식했다. 누적 대화 기록+컨텍스트
데이터(+선택적 화면 스크린샷)를 주고, 호출자가 넘긴 `tools` 함수선언 중 1개를 강제 호출
(mode=ANY)시켜 (tool_name, args) 로 반환한다. 도구 목록이 에이전트마다 달라(expense_card
CHAT_TOOLS, card_collect CARD_COLLECT_TOOLS 등) `tools` 를 파라미터로 받는다 — 이 모듈은
어느 한 에이전트에 종속되지 않는다. 키/모델/베이스는 app.config(Settings)에서 온다.

http 클라이언트는 호출자가 소유·주입한다(재사용). 무료티어 키는 버스트 호출 시
429/일시 오류가 날 수 있어 소폭 retry+지수 backoff 를 둔다(폐기 모델 404 는 즉시 실패).
재시도 소진 시 마지막 예외를 raise → 호출자가 잡아 graceful 안내로 처리한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("app.agents.common.gemini")

# 재시도 대상 상태코드(일시 오류). 404 는 '빈 바디'일 때만 일시로 보고 재시도한다
# (폐기 모델은 바디에 사유가 있어 → 즉시 실패). 429=rate-limit, 5xx=서버 일시 오류.
_RETRY_STATUSES = frozenset({404, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_S = 0.3
_MAX_BACKOFF_S = 2.0


def _backoff_s(attempt: int) -> float:
    """지수 backoff(attempt 1→base, 2→2×base, …). 상한 _MAX_BACKOFF_S."""
    return min(_BASE_BACKOFF_S * (2 ** (attempt - 1)), _MAX_BACKOFF_S)


async def gemini_chat_decide(
    http: Any,
    key: str,
    model: str,
    base: str,
    system: str,
    history: str,
    context: dict,
    shot_b64: str | None,
    tools: list[dict],
) -> tuple[str | None, dict]:
    """대화형 에이전트 한 턴 — 대화 기록+컨텍스트 데이터(+화면)로 `tools` 중 도구 1개를 결정.

    반환: (tool_name, args). 도구 호출이 없으면 (None, {}). 일시 오류는 재시도, 소진 시 raise.
    """
    user_text = (
        f"## 대화/행동 기록\n{history or '(없음)'}\n\n"
        f"## 컨텍스트 데이터\n{json.dumps(context, ensure_ascii=False)}\n\n"
        "첨부 스크린샷(있으면)을 참고해, 사용자의 마지막 입력에 맞는 도구 1개를 호출하세요."
    )
    parts: list[dict] = [{"text": user_text}]
    if shot_b64:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": shot_b64}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "system_instruction": {"parts": [{"text": system}]},
        "tools": [{"functionDeclarations": tools}],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
        "generationConfig": {"temperature": 0.1},
    }
    url = f"{base}/models/{model}:generateContent"
    headers = {"x-goog-api-key": key, "content-type": "application/json"}

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            r = await http.post(url, headers=headers, json=body)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body_txt = (exc.response.text or "").strip()
            # 404+바디 있음(예: '... no longer available') = 폐기 모델 → 즉시 실패(재시도 무의미).
            retryable = status in _RETRY_STATUSES and not (status == 404 and body_txt)
            last_exc = exc
            if retryable and attempt < _MAX_ATTEMPTS:
                logger.warning("gemini %s — 재시도(%s/%s)", status, attempt, _MAX_ATTEMPTS)
                await asyncio.sleep(_backoff_s(attempt))
                continue
            raise
        except httpx.RequestError as exc:  # 네트워크/타임아웃 등 → 일시 오류로 재시도
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                logger.warning("gemini 네트워크 오류 — 재시도(%s/%s): %s", attempt, _MAX_ATTEMPTS, exc)
                await asyncio.sleep(_backoff_s(attempt))
                continue
            raise
        # 성공 — functionCall 파싱.
        cand = (r.json().get("candidates") or [{}])[0]
        for p in (cand.get("content") or {}).get("parts") or []:
            fc = p.get("functionCall")
            if fc:
                return fc.get("name"), fc.get("args") or {}
        return None, {}

    if last_exc is not None:  # 이론상 도달하지 않음(루프에서 raise) — 방어적.
        raise last_exc
    return None, {}
