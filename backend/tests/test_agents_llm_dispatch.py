"""LLM 프로바이더 디스패처(app.agents.common.llm) + etribe 클라이언트 단위테스트(실 LLM 미사용).

- 툴 선언 변환: gemini functionDeclarations → OpenAI tools(파라미터 스키마 보존)
- 분기: settings.llm_provider 로 gemini_*/etribe_* 선택(미보유/기타 값이면 gemini 기본)
- etribe_chat_decide: tool_calls arguments(JSON 문자열)→dict 파싱 + 요청 바디(무사고 모드·
  tool_choice=required·이미지 data URI) 검증
- JSON 폴백: 400 "--tool-call-parser" → response_format json_object 재요청(도구 목록 system
  포함·tools 미포함), content 방어 파싱(펜스/잡텍스트/깨진 JSON), base 별 캐시 직행
- 멀티모달 게이트: settings.etribe_multimodal=False 면 디스패처가 shot 을 None 으로 차단
- etribe_generate_text: message.content 만 반환(reasoning_content 무시)
- 재시도: gemini 와 동일 시맨틱(5xx 후 성공) — backoff 는 gemini 상수 monkeypatch 로 0
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import app.agents.common.etribe as ET
import app.agents.common.gemini as GM
import app.agents.common.llm as LLM


def _resp(status: int, payload: dict | None = None, text: str = "") -> httpx.Response:
    req = httpx.Request("POST", "http://etribe.test/v1/chat/completions")
    if payload is not None:
        return httpx.Response(status, request=req, content=json.dumps(payload).encode())
    return httpx.Response(status, request=req, text=text)


class FakeHttp:
    """post 가 지정한 응답을 순서대로 반환 + 요청 바디를 기록하는 최소 클라이언트."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.urls: list[str] = []
        self.bodies: list[dict] = []

    async def post(self, url: str, headers: Any = None, json: Any = None) -> httpx.Response:
        self.calls += 1
        self.urls.append(url)
        self.bodies.append(json)
        return self._responses.pop(0)


def _tool_resp(name: str, arguments: Any) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "reasoning_content": "사고과정(무시돼야 함)",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                }
            }
        ]
    }


@pytest.fixture(autouse=True)
def _reset_json_fallback_cache(monkeypatch):
    """폴백 base 캐시는 모듈 레벨(프로세스 수명) — 테스트 간 오염 방지로 매번 비운다."""
    monkeypatch.setattr(ET, "_JSON_FALLBACK_BASES", set())


def _settings(provider: str | None) -> SimpleNamespace:
    ns = SimpleNamespace(
        gemini_api_key="gk",
        gemini_model="gm",
        gemini_base_url="http://gemini.test/v1beta",
        etribe_model="Etribe-LLM",
        etribe_base_url="http://etribe.test",
    )
    if provider is not None:
        ns.llm_provider = provider
    return ns


# ── 툴 선언 변환 ───────────────────────────────────────────────────────────────
def test_decls_to_openai_tools_preserves_parameter_schema():
    params = {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {"type": "object", "properties": {"no": {"type": "integer"}}},
            }
        },
        "required": ["recommendations"],
    }
    decls = [{"name": "submit", "description": "제출", "parameters": params}]
    tools = ET.gemini_decls_to_openai_tools(decls)
    assert tools == [
        {
            "type": "function",
            "function": {"name": "submit", "description": "제출", "parameters": params},
        }
    ]
    # parameters(JSON Schema)는 변형 없이 그대로 보존돼야 한다.
    assert tools[0]["function"]["parameters"] is params


def test_decls_to_openai_tools_fills_missing_parameters():
    tools = ET.gemini_decls_to_openai_tools([{"name": "ask"}])
    assert tools[0]["function"]["parameters"] == {"type": "object", "properties": {}}


# ── 디스패처 분기 ──────────────────────────────────────────────────────────────
async def test_dispatch_chat_decide_selects_provider(monkeypatch):
    seen: dict[str, tuple] = {}

    async def fake_g(http, key, model, base, system, history, context, shot, tools, thinking_budget=None, max_output_tokens=None):
        seen["gemini"] = (key, model, base)
        return "g_tool", {"p": 1}

    async def fake_e(http, model, base, system, history, context, shot, tools, max_output_tokens=None):
        seen["etribe"] = (model, base)
        return "e_tool", {"p": 2}

    monkeypatch.setattr(LLM, "gemini_chat_decide", fake_g)
    monkeypatch.setattr(LLM, "etribe_chat_decide", fake_e)

    name, args = await LLM.chat_decide(
        object(), system="s", history="h", context={}, shot_b64=None, tools=[],
        settings=_settings("gemini"),
    )
    assert (name, args) == ("g_tool", {"p": 1})
    assert seen["gemini"] == ("gk", "gm", "http://gemini.test/v1beta")

    name, args = await LLM.chat_decide(
        object(), system="s", history="h", context={}, shot_b64=None, tools=[],
        settings=_settings("etribe"),
    )
    assert (name, args) == ("e_tool", {"p": 2})
    assert seen["etribe"] == ("Etribe-LLM", "http://etribe.test")


async def test_dispatch_defaults_to_gemini_without_provider_attr(monkeypatch):
    called = {"gemini": False}

    async def fake_g(http, key, model, base, system, history, context, shot, tools, thinking_budget=None, max_output_tokens=None):
        called["gemini"] = True
        return None, {}

    monkeypatch.setattr(LLM, "gemini_chat_decide", fake_g)
    # llm_provider 속성이 없는 더미 settings(기존 테스트 관례) → gemini 로 폴백.
    await LLM.chat_decide(
        object(), system="s", history="", context={}, shot_b64=None, tools=[],
        settings=_settings(None),
    )
    assert called["gemini"] is True


async def test_dispatch_generate_text_selects_provider(monkeypatch):
    seen: dict[str, dict] = {}

    async def fake_g(http, key, model, base, *, system, user, temperature, max_output_tokens, thinking_budget=None):
        seen["gemini"] = {"key": key, "thinking_budget": thinking_budget}
        return "g텍스트"

    async def fake_e(http, model, base, *, system, user, temperature, max_output_tokens):
        seen["etribe"] = {"model": model, "max": max_output_tokens}
        return "e텍스트"

    monkeypatch.setattr(LLM, "gemini_generate_text", fake_g)
    monkeypatch.setattr(LLM, "etribe_generate_text", fake_e)

    out = await LLM.generate_text(
        object(), system="s", user="u", thinking_budget=0, settings=_settings("gemini")
    )
    assert out == "g텍스트"
    assert seen["gemini"] == {"key": "gk", "thinking_budget": 0}

    out = await LLM.generate_text(
        object(), system="s", user="u", max_output_tokens=128, settings=_settings("etribe")
    )
    assert out == "e텍스트"
    assert seen["etribe"] == {"model": "Etribe-LLM", "max": 128}


async def test_dispatch_multimodal_gate_blocks_shot_when_disabled(monkeypatch):
    # 텍스트 전용 ETRIBE 서버(etribe_multimodal=False) — 이미지 400 방지를 위해 shot 차단.
    seen: dict[str, Any] = {}

    async def fake_e(http, model, base, system, history, context, shot, tools, max_output_tokens=None):
        seen["shot"] = shot
        return None, {}

    monkeypatch.setattr(LLM, "etribe_chat_decide", fake_e)
    s = _settings("etribe")
    s.etribe_multimodal = False
    await LLM.chat_decide(
        object(), system="s", history="h", context={}, shot_b64="QUJD", tools=[], settings=s
    )
    assert seen["shot"] is None


async def test_dispatch_multimodal_gate_passes_shot_when_enabled(monkeypatch):
    seen: dict[str, Any] = {}

    async def fake_e(http, model, base, system, history, context, shot, tools, max_output_tokens=None):
        seen["shot"] = shot
        return None, {}

    monkeypatch.setattr(LLM, "etribe_chat_decide", fake_e)
    s = _settings("etribe")
    s.etribe_multimodal = True
    await LLM.chat_decide(
        object(), system="s", history="h", context={}, shot_b64="QUJD", tools=[], settings=s
    )
    assert seen["shot"] == "QUJD"

    # 속성 미보유 더미 settings(기존 테스트 관례) → 기본 True 취급으로 통과.
    del seen["shot"]
    await LLM.chat_decide(
        object(), system="s", history="h", context={}, shot_b64="QUJD", tools=[],
        settings=_settings("etribe"),
    )
    assert seen["shot"] == "QUJD"


def test_llm_ready_and_model_name():
    assert LLM.llm_ready(_settings("etribe")) is True  # etribe 는 무인증 — 키 불필요.
    assert LLM.llm_ready(_settings("gemini")) is True
    no_key = _settings("gemini")
    no_key.gemini_api_key = "  "
    assert LLM.llm_ready(no_key) is False  # gemini 는 키 필요(공백만도 없음 취급).
    assert LLM.llm_ready(SimpleNamespace(gemini_api_key="")) is False  # 속성 결손 안전.
    assert LLM.llm_model_name(_settings("etribe")) == "Etribe-LLM"
    assert LLM.llm_model_name(_settings("gemini")) == "gm"


# ── etribe_chat_decide 파싱/바디 ──────────────────────────────────────────────
async def test_etribe_chat_decide_parses_tool_call_and_builds_body():
    http = FakeHttp([_resp(200, _tool_resp("submit", '{"a": 1, "b": "x"}'))])
    decls = [{"name": "submit", "description": "d", "parameters": {"type": "object"}}]
    name, args = await ET.etribe_chat_decide(
        http, "Etribe-LLM", "http://etribe.test", "sys", "hist", {"k": "v"}, "QUJD", decls
    )
    assert name == "submit"
    assert args == {"a": 1, "b": "x"}  # arguments JSON 문자열 → dict.

    assert http.urls == ["http://etribe.test/v1/chat/completions"]
    body = http.bodies[0]
    assert body["model"] == "Etribe-LLM"
    # thinking 서버 기본 ON 유지(2026-07-23 사용자 지시) — 무사고 플래그를 보내지 않는다.
    assert "chat_template_kwargs" not in body
    assert body["tool_choice"] == "auto"  # GLM padding 회피(required→4096토큰 패딩, 2026-07-23).
    assert body["parallel_tool_calls"] is False  # 중복 tool_call emit 방지.
    assert body["tools"][0]["function"]["name"] == "submit"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    # 스크린샷 → content 배열 + jpeg data URI.
    user_content = body["messages"][1]["content"]
    assert user_content[0]["type"] == "text" and "hist" in user_content[0]["text"]
    assert user_content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,QUJD"},
    }


async def test_etribe_chat_decide_no_shot_uses_plain_text_content():
    http = FakeHttp([_resp(200, _tool_resp("ask", "{}"))])
    name, args = await ET.etribe_chat_decide(
        http, "m", "http://etribe.test/", "sys", "", {}, None, [{"name": "ask"}]
    )
    assert (name, args) == ("ask", {})
    assert isinstance(http.bodies[0]["messages"][1]["content"], str)  # 이미지 없으면 순수 텍스트.
    assert http.urls == ["http://etribe.test/v1/chat/completions"]  # base 끝 슬래시 정리.


async def test_etribe_chat_decide_without_tool_call_returns_none():
    http = FakeHttp([_resp(200, {"choices": [{"message": {"content": "그냥 텍스트"}}]})])
    name, args = await ET.etribe_chat_decide(
        http, "m", "http://b", "s", "h", {}, None, [{"name": "ask"}]
    )
    assert name is None
    assert args == {}


async def test_etribe_chat_decide_bad_arguments_json_returns_empty_args():
    http = FakeHttp([_resp(200, _tool_resp("submit", "{broken"))])
    name, args = await ET.etribe_chat_decide(
        http, "m", "http://b", "s", "h", {}, None, [{"name": "submit"}]
    )
    assert name == "submit"
    assert args == {}  # 파싱 실패 → 빈 args(호출부 계약 유지: dict 보장).


async def test_etribe_chat_decide_max_output_tokens_overrides_default():
    """max_output_tokens 명시 시 결정 상한 _DECIDE_MAX_TOKENS 대신 그 값이 나간다(미명시=기본)."""
    http = FakeHttp([_resp(200, _tool_resp("ask", "{}"))])
    await ET.etribe_chat_decide(
        http, "m", "http://b", "s", "h", {}, None, [{"name": "ask"}], max_output_tokens=16_384
    )
    assert http.bodies[0]["max_tokens"] == 16_384

    http2 = FakeHttp([_resp(200, _tool_resp("ask", "{}"))])
    await ET.etribe_chat_decide(http2, "m", "http://b", "s", "h", {}, None, [{"name": "ask"}])
    assert http2.bodies[0]["max_tokens"] == ET._DECIDE_MAX_TOKENS


async def test_dispatch_chat_decide_threads_max_output_tokens(monkeypatch):
    """디스패처가 max_output_tokens 를 두 프로바이더 구현에 그대로 전달한다."""
    seen: dict[str, Any] = {}

    async def fake_g(http, key, model, base, system, history, context, shot, tools, thinking_budget=None, max_output_tokens=None):
        seen["gemini"] = max_output_tokens
        return None, {}

    async def fake_e(http, model, base, system, history, context, shot, tools, max_output_tokens=None):
        seen["etribe"] = max_output_tokens
        return None, {}

    monkeypatch.setattr(LLM, "gemini_chat_decide", fake_g)
    monkeypatch.setattr(LLM, "etribe_chat_decide", fake_e)
    await LLM.chat_decide(
        object(), system="s", history="", context={}, shot_b64=None, tools=[],
        settings=_settings("gemini"), max_output_tokens=16_384,
    )
    await LLM.chat_decide(
        object(), system="s", history="", context={}, shot_b64=None, tools=[],
        settings=_settings("etribe"), max_output_tokens=16_384,
    )
    assert seen == {"gemini": 16_384, "etribe": 16_384}


# ── JSON 모드 폴백(네이티브 툴콜 미지원 서버) ─────────────────────────────────
_PARSER_400 = (
    '{"object":"error","message":"\\"auto\\" tool choice requires --tool-call-parser '
    'to be set","type":"BadRequestError","code":400}'
)


def _json_resp(content: str) -> dict:
    return {"choices": [{"message": {"content": content, "reasoning": "사고(무시)"}}]}


async def test_etribe_fallback_triggers_on_parser_400_and_rebuilds_request():
    http = FakeHttp(
        [
            _resp(400, text=_PARSER_400),
            _resp(200, _json_resp('{"tool": "submit", "args": {"a": 1}}')),
        ]
    )
    decls = [{"name": "submit", "description": "제출 도구", "parameters": {"type": "object"}}]
    name, args = await ET.etribe_chat_decide(
        http, "Etribe-VLM", "http://etribe.test", "sys", "hist", {}, None, decls
    )
    assert (name, args) == ("submit", {"a": 1})
    assert http.calls == 2  # 1차 네이티브 400 → 2차 JSON 폴백.

    first, second = http.bodies
    assert first["tool_choice"] == "auto"  # 1차 네이티브 경로(GLM padding 회피).
    # 2차: tools/tool_choice 없이 response_format json_object + system 에 도구 목록.
    assert "tools" not in second and "tool_choice" not in second
    assert second["response_format"] == {"type": "json_object"}
    sys_msg = second["messages"][0]["content"]
    assert sys_msg.startswith("sys")  # 원 system 유지 + 도구 목록/지시 덧붙임.
    assert '"submit"' in sys_msg and "제출 도구" in sys_msg
    assert '{"tool": "<도구명>", "args": {...}}' in sys_msg
    assert second["messages"][1]["content"] == first["messages"][1]["content"]  # user 동일.


async def test_etribe_fallback_cache_skips_native_roundtrip():
    # 1회차에서 폴백 발동 → 캐시 기록.
    http1 = FakeHttp(
        [_resp(400, text=_PARSER_400), _resp(200, _json_resp('{"tool": "ask", "args": {}}'))]
    )
    await ET.etribe_chat_decide(http1, "m", "http://etribe.test", "s", "h", {}, None, [{"name": "ask"}])
    assert "http://etribe.test" in ET._JSON_FALLBACK_BASES

    # 2회차: 같은 base 는 400 왕복 없이 JSON 폴백 직행(요청 1회).
    http2 = FakeHttp([_resp(200, _json_resp('{"tool": "ask", "args": {"q": "x"}}'))])
    name, args = await ET.etribe_chat_decide(
        http2, "m", "http://etribe.test", "s", "h", {}, None, [{"name": "ask"}]
    )
    assert (name, args) == ("ask", {"q": "x"})
    assert http2.calls == 1
    assert http2.bodies[0]["response_format"] == {"type": "json_object"}


async def test_etribe_400_without_parser_marker_still_raises():
    # 폴백은 tool-call-parser 문구가 있는 400 에만 발동 — 다른 400 은 기존대로 raise.
    http = FakeHttp([_resp(400, text='{"message": "bad request"}')])
    with pytest.raises(httpx.HTTPStatusError):
        await ET.etribe_chat_decide(http, "m", "http://b", "s", "h", {}, None, [{"name": "ask"}])
    assert ET._JSON_FALLBACK_BASES == set()


def test_parse_tool_json_strips_code_fence_and_junk():
    tools = [{"name": "ask"}]
    # 코드펜스 포함.
    assert ET._parse_tool_json('```json\n{"tool": "ask", "args": {"x": 1}}\n```', tools) == (
        "ask",
        {"x": 1},
    )
    # 앞뒤 잡텍스트 — 첫 여는 중괄호부터 raw_decode(뒤 잔여 허용).
    assert ET._parse_tool_json(
        '알겠습니다. {"tool": "ask", "args": {}} 위와 같이 호출합니다.', tools
    ) == ("ask", {})


def test_parse_tool_json_invalid_inputs_return_none():
    tools = [{"name": "ask"}]
    assert ET._parse_tool_json('{"tool": broken', tools) == (None, {})  # 깨진 JSON.
    assert ET._parse_tool_json("도구 없이 텍스트만", tools) == (None, {})  # 중괄호 없음.
    assert ET._parse_tool_json('{"tool": "nope", "args": {}}', tools) == (None, {})  # 미존재 도구.
    assert ET._parse_tool_json('{"args": {}}', tools) == (None, {})  # tool 키 없음.
    # args 가 dict 아님 → 빈 args 로 방어(호출부 dict 계약).
    assert ET._parse_tool_json('{"tool": "ask", "args": [1]}', tools) == ("ask", {})


# ── etribe_generate_text ──────────────────────────────────────────────────────
async def test_etribe_generate_text_returns_content_ignores_reasoning():
    payload = {
        "choices": [
            {"message": {"content": "  야근식대(법인카드)  ", "reasoning_content": "긴 사고"}}
        ]
    }
    http = FakeHttp([_resp(200, payload)])
    out = await ET.etribe_generate_text(
        http, "Etribe-LLM", "http://etribe.test", system="s", user="u", max_output_tokens=128
    )
    assert out == "야근식대(법인카드)"  # reasoning_content 무시 + 앞뒤 공백 정리.
    body = http.bodies[0]
    # thinking ON: 사고 토큰이 completion 예산을 공유 → 요청치 + 사고 헤드룸(1024).
    assert body["max_tokens"] == 128 + ET._THINKING_HEADROOM_TOKENS
    # 무사고 플래그를 보내지 않는다(서버 기본 ON — 2026-07-23 사용자 지시).
    assert "chat_template_kwargs" not in body


async def test_etribe_generate_text_empty_content_returns_none():
    http = FakeHttp([_resp(200, {"choices": [{"message": {"content": ""}}]})])
    out = await ET.etribe_generate_text(http, "m", "http://b", system="s", user="u")
    assert out is None


# ── 재시도(gemini 동일 시맨틱) ─────────────────────────────────────────────────
async def test_etribe_retries_on_5xx_then_succeeds(monkeypatch):
    # backoff 상수는 gemini 모듈 소유(_backoff_s 재사용) — 0 으로 즉시 진행.
    monkeypatch.setattr(GM, "_BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(GM, "_MAX_BACKOFF_S", 0.0)
    http = FakeHttp([_resp(500, text="oops"), _resp(200, _tool_resp("ask", "{}"))])
    name, _args = await ET.etribe_chat_decide(
        http, "m", "http://b", "s", "h", {}, None, [{"name": "ask"}]
    )
    assert name == "ask"
    assert http.calls == 2  # 500 1회 후 재시도 성공.


async def test_etribe_retries_exhaust_then_raises(monkeypatch):
    monkeypatch.setattr(GM, "_BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(GM, "_MAX_BACKOFF_S", 0.0)
    http = FakeHttp([_resp(503), _resp(503), _resp(503)])
    with pytest.raises(httpx.HTTPStatusError):
        await ET.etribe_generate_text(http, "m", "http://b", system="s", user="u")
    assert http.calls == GM._MAX_ATTEMPTS  # 최대 시도 소진(gemini 와 동일).
