"""LLM 프로바이더 디스패처(app.agents.common.llm) + etribe 클라이언트 단위테스트(실 LLM 미사용).

- 툴 선언 변환: gemini functionDeclarations → OpenAI tools(파라미터 스키마 보존)
- 분기: settings.llm_provider 로 gemini_*/etribe_* 선택(미보유/기타 값이면 gemini 기본)
- etribe_chat_decide: tool_calls arguments(JSON 문자열)→dict 파싱 + 요청 바디(무사고 모드·
  tool_choice=required·이미지 data URI) 검증
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

    async def fake_g(http, key, model, base, system, history, context, shot, tools):
        seen["gemini"] = (key, model, base)
        return "g_tool", {"p": 1}

    async def fake_e(http, model, base, system, history, context, shot, tools):
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

    async def fake_g(http, key, model, base, system, history, context, shot, tools):
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
    assert body["chat_template_kwargs"] == {"thinking_mode": "disabled"}  # 무사고 모드.
    assert body["tool_choice"] == "required"  # gemini ANY 동치(강제 툴콜).
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
    assert body["max_tokens"] == 128
    assert body["chat_template_kwargs"] == {"thinking_mode": "disabled"}


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
