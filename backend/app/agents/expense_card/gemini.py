"""Gemini 비전 function-calling 한 턴 — 대화형 폼 에이전트의 판단 호출.

ninebell-bak `erp/graph.py` 의 `_gemini_chat_decide` 를 이식했다. 화면 스크린샷(선택)+
누적 대화 기록+선행학습 폼 스키마를 주고, `_CHAT_TOOLS` 중 도구 1개를 강제 호출(mode=ANY)
시켜 (tool_name, args) 로 반환한다. 키/모델/베이스는 app.config(Settings)에서 온다.

http 클라이언트는 호출자(chat_form)가 소유·주입한다(재사용). 실패는 호출자가 잡아
graceful 처리한다(여기서는 raise_for_status 로 승격).
"""

from __future__ import annotations

import json
from typing import Any

from .tools import CHAT_TOOLS


async def gemini_chat_decide(
    http: Any,
    key: str,
    model: str,
    base: str,
    system: str,
    history: str,
    schema: dict,
    shot_b64: str | None,
) -> tuple[str | None, dict]:
    """채팅형 폼 에이전트 한 턴 — 대화 기록+화면으로 도구 1개를 결정.

    반환: (tool_name, args). 도구 호출이 없으면 (None, {}).
    """
    user_text = (
        f"## 대화/행동 기록\n{history or '(없음)'}\n\n"
        f"## 현재 모달 폼 스키마(선행학습)\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        "첨부 스크린샷을 참고해, 사용자의 마지막 입력을 필드로 매핑하고 다음 행동 1개를 도구로 호출하세요."
    )
    parts: list[dict] = [{"text": user_text}]
    if shot_b64:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": shot_b64}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "system_instruction": {"parts": [{"text": system}]},
        "tools": [{"functionDeclarations": CHAT_TOOLS}],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
        "generationConfig": {"temperature": 0.1},
    }
    r = await http.post(
        f"{base}/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "content-type": "application/json"},
        json=body,
    )
    r.raise_for_status()
    cand = (r.json().get("candidates") or [{}])[0]
    for p in (cand.get("content") or {}).get("parts") or []:
        fc = p.get("functionCall")
        if fc:
            return fc.get("name"), fc.get("args") or {}
    return None, {}
