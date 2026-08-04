"""사내 Etribe-LLM(OpenAI /v1/chat/completions 호환) 클라이언트 — 온프렘 프로바이더.

:mod:`app.agents.common.gemini` 의 `gemini_chat_decide`/`gemini_generate_text` 와 **동일한
반환 계약**을 지킨다 — 호출부는 프로바이더 분기를 모른다(:mod:`app.agents.common.llm`
디스패처가 선택). 비스트리밍 POST 1회. thinking 은 **서버 기본 ON 을 그대로 쓴다**
(2026-07-23 사용자 지시로 무사고 모드 해제 — 사내 서버라 토큰 부담 없음, 품질 우선. 짧은
생성은 사고가 max_tokens 를 잠식하지 않게 _THINKING_HEADROOM_TOKENS 를 더한다). 응답의
`reasoning_content` 채널은 사고과정이므로 무시하고 `message.tool_calls`/`message.content`
만 파싱한다. 인증은 없음(키 아무 값) — OpenAI 호환 미들웨어 호환을 위해 더미 Bearer 를 보낸다.

재시도/backoff 는 gemini 모듈과 동일 시맨틱 — 상수(_RETRY_STATUSES/_MAX_ATTEMPTS)와
_backoff_s 를 그대로 재사용한다(테스트에서 gemini 쪽 backoff monkeypatch 가 함께 적용).

툴콜은 이중 경로: 1차 네이티브 tools+tool_choice=required(다른 ETRIBE 서버 호환 유지),
서버가 400 "--tool-call-parser" 로 거부하면(현행 ETRIBE-VLM 실측 2026-07-23) JSON 모드
폴백(response_format json_object) — 이후 호출은 base 별 캐시로 폴백 직행한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.agents.common.gemini import _MAX_ATTEMPTS, _RETRY_STATUSES, _backoff_s
from app.agents.common.prompt_capture import capture_request, capture_response

logger = logging.getLogger("app.agents.common.etribe")

# 인증 없음(가이드) — 일부 OpenAI 호환 게이트웨이가 헤더 존재를 요구할 수 있어 더미를 넣는다.
_HEADERS = {"content-type": "application/json", "authorization": "Bearer etribe"}

# thinking ON 에서 사고 토큰은 completion(max_tokens) 예산을 공유한다 — 짧은 생성(적요 256)이
# 사고에 잠식돼 빈 content 로 끝나지 않도록 요청 max_tokens 에 더하는 사고 헤드룸.
_THINKING_HEADROOM_TOKENS = 1_024

# 결정(도구 선택) 호출 max_tokens 상한 — 사고 ON 서버(GLM-5.2 등)는 상한이 없으면 도구 호출
# 직전까지 사고를 무제한 생성해 httpx 타임아웃(네트워크 오류 재시도 루프)에 빠진다(2026-07-23
# 172.20 GLM 스모크 실측). 사고 헤드룸 + 도구 호출 JSON 여유. 네이티브·JSON 폴백 공통.
# ⚠ 2048 은 1행 판단만으로도 finish_reason=length(사고가 상한 소진) 관측 — 다행 여러 행에서도
# 툴콜은 통과했으나 잘림 위험이라 4096 으로 상향(GLM max_model_len 262144 로 여유 충분).
_DECIDE_MAX_TOKENS = 4_096

# 네이티브 툴콜 미지원 서버의 400 바디 식별 문구(vLLM: "...requires --tool-call-parser...").
_TOOL_PARSER_MARKER = "tool-call-parser"

# 네이티브 툴콜 미지원으로 판명된 base 캐시 — 이후 호출은 JSON 폴백 직행(매 호출 400 왕복
# 방지). 프로세스 재시작 시 리셋 → 서버 교체/업그레이드를 자연 재탐지한다.
_JSON_FALLBACK_BASES: set[str] = set()


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
    cap_seq = capture_request("etribe", url, body)  # 전체 프롬프트 캡처(env 게이트, best-effort)
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
        data = r.json()
        capture_response("etribe", url, cap_seq, data)  # LLM 응답 캡처(요청과 seq 로 짝).
        return data

    if last_exc is not None:  # 이론상 도달하지 않음(루프에서 raise) — 방어적(gemini 와 동일).
        raise last_exc
    return {}


def _tools_catalog_json(tools: list[dict]) -> str:
    """JSON 폴백 system 에 덧붙일 도구 목록 — name/description/parameters(JSON Schema) 보존."""
    return json.dumps(
        [
            {
                "name": d.get("name") or "",
                "description": d.get("description") or "",
                "parameters": d.get("parameters") or {"type": "object", "properties": {}},
            }
            for d in tools
        ],
        ensure_ascii=False,
    )


def _parse_tool_json(text: str, tools: list[dict]) -> tuple[str | None, dict]:
    """JSON 폴백 응답 content → (name, args). 방어적 파싱 + tool/args 키 검증.

    코드펜스를 걷어내고 첫 여는 중괄호부터 raw_decode(뒤쪽 잡텍스트 허용)한다.
    파싱 실패/`tool` 이 선언 목록에 없음 → (None, {}) — 네이티브 경로의 '도구 호출 없음'
    계약과 동일(호출부의 기존 휴리스틱 폴백이 무해하게 받는다).
    """
    raw = (text or "").strip()
    if raw.startswith("```"):  # ```json ... ``` — 헤더 줄과 닫는 펜스를 제거.
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        end = raw.rfind("```")
        if end != -1:
            raw = raw[:end]
    start = raw.find("{")
    if start == -1:
        return None, {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
    except ValueError:
        logger.warning("etribe JSON 폴백 content 파싱 실패 — (None, {}) 반환")
        return None, {}
    if not isinstance(obj, dict):
        return None, {}
    name = obj.get("tool")
    if not isinstance(name, str) or name not in {d.get("name") for d in tools}:
        logger.warning("etribe JSON 폴백 도구명 검증 실패(%r) — (None, {}) 반환", name)
        return None, {}
    args = obj.get("args")
    return name, args if isinstance(args, dict) else {}


async def _decide_via_json_mode(
    http: Any,
    model: str,
    base: str,
    system: str,
    content: Any,
    tools: list[dict],
    max_tokens: int = _DECIDE_MAX_TOKENS,
) -> tuple[str | None, dict]:
    """네이티브 툴콜 미지원 서버용 폴백 — response_format json_object 로 도구 선택 강제.

    tools/tool_choice 없이 system 에 도구 목록과 출력 형식을 지시하고, content(JSON 객체
    하나)를 파싱해 (name, args) 를 반환한다. response_format 은 현행 ETRIBE-VLM 실측 OK.
    """
    fallback_system = (
        f"{system}\n\n"
        "## 사용 가능 도구 목록(JSON)\n"
        f"{_tools_catalog_json(tools)}\n\n"
        "위 도구 중 사용자의 마지막 입력에 맞는 도구 1개를 골라, 아래 형식의 JSON 객체 "
        '하나만 출력하세요: {"tool": "<도구명>", "args": {...}} — args 는 해당 도구의 '
        "parameters 스키마를 따르고, 다른 텍스트·코드펜스는 금지합니다."
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": fallback_system},
            {"role": "user", "content": content},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,  # 사고 무제한 생성 방지(네이티브 경로와 동일).
        "response_format": {"type": "json_object"},
    }
    data = await _post_chat(http, base, body, tag="decide-json")
    msg = ((data.get("choices") or [{}])[0].get("message")) or {}
    # reasoning(사고과정 채널)은 무시하고 content 만 파싱한다(기존 규칙).
    return _parse_tool_json(msg.get("content") or "", tools)


async def etribe_chat_decide(
    http: Any,
    model: str,
    base: str,
    system: str,
    history: str,
    context: dict,
    shot_b64: str | None,
    tools: list[dict],
    *,
    max_output_tokens: int | None = None,
) -> tuple[str | None, dict]:
    """`gemini_chat_decide` 와 동일 계약 — `tools` 중 도구 1개를 강제 호출시켜 (name, args) 반환.

    max_output_tokens 가 주어지면 결정 호출 상한 _DECIDE_MAX_TOKENS(4096) 대신 그 값을
    max_tokens 로 쓴다(대량 배치 판단용 — JSON 폴백 경로에도 동일 적용).

    1차는 네이티브 tools+tool_choice='required'(gemini toolConfig mode=ANY 동치 — 다른
    ETRIBE 서버 호환 유지). 서버가 400 "--tool-call-parser" 로 거부하면 JSON 모드 폴백으로
    재요청하고, base 별 캐시에 기억해 이후 호출은 폴백 직행한다. 도구 호출이 없으면 (None, {}).
    thinking 은 서버 기본 ON(2026-07-23 사용자 지시 — 사내 서버라 토큰 부담 없음, 품질 우선).
    사고과정은 reasoning_content 채널로 오고 최종 답은 tool_calls 라 파싱은 동일하다.
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
    oa_tools = gemini_decls_to_openai_tools(tools)
    base_key = base.rstrip("/")
    max_tokens = _DECIDE_MAX_TOKENS if max_output_tokens is None else max_output_tokens
    if oa_tools and base_key in _JSON_FALLBACK_BASES:
        # 네이티브 툴콜 미지원으로 이미 판명된 서버 — 400 왕복 없이 폴백 직행.
        return await _decide_via_json_mode(
            http, model, base, system, content, tools, max_tokens=max_tokens
        )

    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,  # 사고 무제한 생성 방지(타임아웃 회피).
        # thinking 서버 기본 ON 유지(가이드 §4 — 미전송 시 ON). 사고과정(reasoning_content)은
        # 파싱에서 무시하고 tool_calls 만 읽는다. (2026-07-23 무사고→사고 전환, 사용자 지시)
    }
    if oa_tools:  # 빈 tools 로 tool_choice 를 보내면 OpenAI 규격 오류 — 방어적 가드.
        body["tools"] = oa_tools
        # ⚠ tool_choice='auto' — 'required' 는 GLM(vLLM)에서 도구 호출 후에도 정지 토큰을 안 내고
        # max_tokens 까지 무의미한 패딩을 채워 매 호출이 4096 토큰·finish=length 가 된다(2026-07-23
        # 실측: required→4096 / auto→~230, 툴콜 유효·finish=tool_calls, 17배 절감). 강한 프롬프트
        # ('정확히 1회 호출')로 실호출은 보장되고, 미호출 시엔 (None,{})→호출부 폴백(무해).
        body["tool_choice"] = "auto"
        body["parallel_tool_calls"] = False  # 동일 도구 중복 emit 방지(GLM 이 7회까지 반복 관측).

    try:
        data = await _post_chat(http, base, body, tag="decide")
    except httpx.HTTPStatusError as exc:
        body_txt = exc.response.text or ""
        if oa_tools and exc.response.status_code == 400 and _TOOL_PARSER_MARKER in body_txt:
            # 서버가 네이티브 툴콜 파서 미설정(현행 ETRIBE-VLM 실측) — JSON 폴백으로 흡수.
            _JSON_FALLBACK_BASES.add(base_key)
            logger.info("etribe 네이티브 툴콜 미지원(%s) — JSON 모드 폴백 전환", base_key)
            return await _decide_via_json_mode(
                http, model, base, system, content, tools, max_tokens=max_tokens
            )
        raise
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
    thinking 은 서버 기본 ON(2026-07-23 사용자 지시). 사고 토큰이 completion 예산
    (max_tokens)을 공유하므로 짧은 생성(적요 256 등)이 사고에 잠식돼 빈 응답이 되지 않게
    헤드룸을 더한다 — 실제 출력 길이는 프롬프트 지시가 계속 제한한다. 그래도 비면 None
    반환 → 호출부의 휴리스틱 폴백이 무해하게 받는다(기존 계약).
    """
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_output_tokens + _THINKING_HEADROOM_TOKENS,
    }
    data = await _post_chat(http, base, body, tag="text")
    msg = ((data.get("choices") or [{}])[0].get("message")) or {}
    text = (msg.get("content") or "").strip()
    return text or None
