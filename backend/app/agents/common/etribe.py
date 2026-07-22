"""사내 Etribe-LLM(OpenAI /v1/chat/completions 호환) 클라이언트 — 온프렘 프로바이더.

:mod:`app.agents.common.gemini` 의 `gemini_chat_decide`/`gemini_generate_text` 와 **동일한
반환 계약**을 지킨다 — 호출부는 프로바이더 분기를 모른다(:mod:`app.agents.common.llm`
디스패처가 선택). 비스트리밍 POST 1회. thinking 은 서버 기본 ON 이라 결정/짧은 생성엔
불필요 — `chat_template_kwargs.thinking_mode='disabled'` 로 끈다(API 가이드 §4). 응답의
`reasoning_content` 채널은 사고과정이므로 무시하고 `message.tool_calls`/`message.content`
만 파싱한다. 인증은 없음(키 아무 값) — OpenAI 호환 미들웨어 호환을 위해 더미 Bearer 를 보낸다.

재시도/backoff 는 gemini 모듈과 동일 시맨틱 — 상수(_RETRY_STATUSES/_MAX_ATTEMPTS)와
_backoff_s 를 그대로 재사용한다(테스트에서 gemini 쪽 backoff monkeypatch 가 함께 적용).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.agents.common.gemini import _MAX_ATTEMPTS, _RETRY_STATUSES, _backoff_s

logger = logging.getLogger("app.agents.common.etribe")

# 인증 없음(가이드) — 일부 OpenAI 호환 게이트웨이가 헤더 존재를 요구할 수 있어 더미를 넣는다.
_HEADERS = {"content-type": "application/json", "authorization": "Bearer etribe"}


def gemini_decls_to_openai_tools(decls: list[dict]) -> list[dict]:
    """Gemini functionDeclarations([{name,description,parameters}]) → OpenAI tools 변환.

    parameters(JSON Schema)는 두 규격이 같은 모양이라 **그대로 보존**한다. 호출부의 기존
    도구 선언(CHAT_TOOLS, _TOOLS 등)을 손대지 않기 위한 어댑터.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": d.get("name") or "",
                "description": d.get("description") or "",
                "parameters": d.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for d in decls
    ]


async def _post_chat(http: Any, base: str, body: dict, *, tag: str) -> dict:
    """POST /v1/chat/completions — gemini 와 동일한 재시도 시맨틱으로 성공 JSON 을 반환.

    일시 오류(_RETRY_STATUSES·네트워크)는 재시도, 소진 시 마지막 예외 raise(호출자가 잡아
    폴백/안내). gemini 와 동일하게 404+바디 있음(경로/모델 오설정 등 명확 사유)은 즉시 실패.
    """
    url = f"{base.rstrip('/')}/v1/chat/completions"
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            r = await http.post(url, headers=_HEADERS, json=body)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body_txt = (exc.response.text or "").strip()
            if status == 400 and "context_length_exceeded" in body_txt:
                # 가이드 §4: 한도 초과는 재시도 무의미(서버 무상태) — 명확한 한국어 사유로
                # 즉시 실패해 호출자 로그에 handoff 힌트를 남긴다(assistant 라우터와 동일 취지).
                raise RuntimeError(
                    "대화가 모델 컨텍스트 한도를 초과했습니다(context_length_exceeded) — "
                    "이전 내용을 요약해 새 대화로 이어가 주세요."
                ) from exc
            retryable = status in _RETRY_STATUSES and not (status == 404 and body_txt)
            last_exc = exc
            if retryable and attempt < _MAX_ATTEMPTS:
                logger.warning("etribe %s %s — 재시도(%s/%s)", tag, status, attempt, _MAX_ATTEMPTS)
                await asyncio.sleep(_backoff_s(attempt))
                continue
            raise
        except httpx.RequestError as exc:  # 네트워크/타임아웃 등 → 일시 오류로 재시도
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "etribe %s 네트워크 오류 — 재시도(%s/%s): %s", tag, attempt, _MAX_ATTEMPTS, exc
                )
                await asyncio.sleep(_backoff_s(attempt))
                continue
            raise
        return r.json()

    if last_exc is not None:  # 이론상 도달하지 않음(루프에서 raise) — 방어적(gemini 와 동일).
        raise last_exc
    return {}


async def etribe_chat_decide(
    http: Any,
    model: str,
    base: str,
    system: str,
    history: str,
    context: dict,
    shot_b64: str | None,
    tools: list[dict],
) -> tuple[str | None, dict]:
    """`gemini_chat_decide` 와 동일 계약 — `tools` 중 도구 1개를 강제 호출시켜 (name, args) 반환.

    tool_choice='required' 가 gemini toolConfig mode=ANY 동치. 도구 호출이 없으면 (None, {}).
    결정 호출은 빠른 무사고 모드(thinking disabled) — 이미지 첨부 시 서버가 자동으로 켜도
    최종 답은 tool_calls 로 오므로 파싱은 동일하다.
    """
    user_text = (
        f"## 대화/행동 기록\n{history or '(없음)'}\n\n"
        f"## 컨텍스트 데이터\n{json.dumps(context, ensure_ascii=False)}\n\n"
        "첨부 스크린샷(있으면)을 참고해, 사용자의 마지막 입력에 맞는 도구 1개를 호출하세요."
    )
    content: Any = user_text
    if shot_b64:  # chat_form 스크린샷은 page.screenshot(type='jpeg') — data URI 로 첨부(가이드 §3).
        content = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{shot_b64}"}},
        ]
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "temperature": 0.1,
        # 결정 호출은 빠른 무사고 모드(가이드 §4). 사고과정(reasoning_content)은 파싱에서 무시.
        "chat_template_kwargs": {"thinking_mode": "disabled"},
    }
    oa_tools = gemini_decls_to_openai_tools(tools)
    if oa_tools:  # 빈 tools 로 tool_choice 를 보내면 OpenAI 규격 오류 — 방어적 가드.
        body["tools"] = oa_tools
        body["tool_choice"] = "required"  # gemini toolConfig mode=ANY 동치 — 반드시 도구 호출.

    data = await _post_chat(http, base, body, tag="decide")
    msg = ((data.get("choices") or [{}])[0].get("message")) or {}
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        raw = fn.get("arguments")
        if isinstance(raw, dict):  # 일부 호환 서버는 이미 dict 로 준다 — 그대로 사용.
            return name, raw
        try:
            args = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            logger.warning("etribe tool_call arguments JSON 파싱 실패 — 빈 args 로 대체")
            args = {}
        return name, args if isinstance(args, dict) else {}
    return None, {}


async def etribe_generate_text(
    http: Any,
    model: str,
    base: str,
    *,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_output_tokens: int = 256,
) -> str | None:
    """`gemini_generate_text` 와 동일 계약 — 순수 텍스트 응답 1개(message.content)만 반환.

    reasoning_content(사고과정 채널)는 응답이 아니므로 무시. 텍스트가 없으면 None.
    무사고 모드라 gemini 의 thinking_budget 에 해당하는 별도 파라미터는 필요 없다.
    """
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_output_tokens,
        "chat_template_kwargs": {"thinking_mode": "disabled"},
    }
    data = await _post_chat(http, base, body, tag="text")
    msg = ((data.get("choices") or [{}])[0].get("message")) or {}
    text = (msg.get("content") or "").strip()
    return text or None
