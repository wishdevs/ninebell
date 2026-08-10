"""EtribeProvider 단위테스트 — SSE 스트림을 httpx.MockTransport 로 목킹(실서버 미사용).

- 텍스트 델타 순서 보존 + [DONE] 종료(done 1회, 마지막 프레임).
- reasoning_content(사고 과정 채널) 스킵.
- 툴콜 arguments 조각 누적 → 완성 시점 1회 방출(Gemini 와 같은 {"name","args"} 모양).
- HTTP 400 context_length_exceeded → 한국어 안내(요약 후 새 대화 힌트) 래핑.
- assistant 라우터 분기: llm_provider='etribe' 면 EtribeProvider, 기본은 GeminiProvider.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

import app.routers.assistant as assistant
from app.config import Settings
from app.llm.base import ChatMessage
from app.llm.etribe import ContextLengthExceededError, EtribeProvider
from app.llm.gemini import GeminiProvider


def _chunk(delta: dict, finish: str | None = None) -> str:
    """OpenAI chat.completion.chunk 프레임 1개(JSON 문자열)."""
    return json.dumps(
        {"choices": [{"delta": delta, "finish_reason": finish}]}, ensure_ascii=False
    )


def _sse(*events: str) -> bytes:
    return "".join(f"data: {e}\n\n" for e in events).encode()


def _provider_for(body: bytes, status: int = 200) -> EtribeProvider:
    """지정한 바디를 SSE 로 흘리는 MockTransport 클라이언트 위의 프로바이더."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, content=body, headers={"content-type": "text/event-stream"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EtribeProvider(client, model="Etribe-LLM", base_url="http://etribe.test")


async def _collect(provider: EtribeProvider) -> list:
    msgs = [ChatMessage(role="user", content="안녕")]
    return [c async for c in provider.chat(msgs, system="테스트 시스템")]


async def test_text_deltas_preserve_order_and_done_last():
    body = _sse(
        _chunk({"content": "안녕"}),
        _chunk({"content": "하세요"}),
        _chunk({}, finish="stop"),
        "[DONE]",
    )
    chunks = await _collect(_provider_for(body))
    assert [c.delta for c in chunks if c.delta] == ["안녕", "하세요"]  # 순서 보존
    dones = [c for c in chunks if c.done]
    assert len(dones) == 1  # done 은 정확히 1회(중복 [DONE] 방지)
    assert dones[0].finish_reason == "stop"
    assert chunks[-1].done  # done 이 마지막 프레임


async def test_reasoning_content_skipped():
    # thinking 기본 ON — 사고 과정은 reasoning_content 채널로 온다. 응답(delta)에 섞이면 안 된다.
    body = _sse(
        _chunk({"reasoning_content": "사고 과정..."}),
        _chunk({"content": "최종 답변", "reasoning_content": "잔여 사고"}),
        _chunk({}, finish="stop"),
        "[DONE]",
    )
    chunks = await _collect(_provider_for(body))
    assert [c.delta for c in chunks if c.delta] == ["최종 답변"]
    assert all("사고" not in c.delta for c in chunks)


async def test_tool_call_fragments_accumulate_then_emit_once():
    # OpenAI 스트리밍 툴콜: name 은 첫 조각, arguments 는 문자열 조각으로 분할되어 온다.
    body = _sse(
        _chunk({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "suggest_agent", "arguments": ""}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"agentId":'}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"a1","intent":"open"}'}}]}),
        _chunk({}, finish="tool_calls"),
        "[DONE]",
    )
    chunks = await _collect(_provider_for(body))
    tool_chunks = [c for c in chunks if c.tool_call]
    assert len(tool_chunks) == 1  # 조각 누적 → 1회 방출
    # GeminiProvider 의 functionCall 방출과 같은 모양: {"name": str, "args": dict}
    assert tool_chunks[0].tool_call == {
        "name": "suggest_agent",
        "args": {"agentId": "a1", "intent": "open"},
    }
    assert chunks[-1].done and chunks[-1].finish_reason == "tool_calls"  # done 은 툴콜 뒤


async def test_context_length_exceeded_wrapped_in_korean():
    err = json.dumps(
        {"error": {"message": "too long", "code": "context_length_exceeded"}}
    ).encode()
    provider = _provider_for(err, status=400)
    with pytest.raises(ContextLengthExceededError) as ei:
        await _collect(provider)
    # 가이드 권고(요약 후 새 세션 handoff) 힌트가 한국어 메시지에 담겨야 한다.
    assert "컨텍스트 한도" in str(ei.value)
    assert "요약" in str(ei.value)


async def test_other_http_error_mirrors_gemini_convention():
    provider = _provider_for(b"internal error", status=500)
    with pytest.raises(httpx.HTTPStatusError):
        await _collect(provider)


async def test_done_without_finish_reason_still_terminates():
    # finish_reason 없이 [DONE] 만 와도 보강 done 으로 스트림이 정상 종료된다.
    body = _sse(_chunk({"content": "부분"}), "[DONE]")
    chunks = await _collect(_provider_for(body))
    assert len(chunks) == 2
    assert chunks[-1].done and chunks[-1].finish_reason is None


def _fake_request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http=object())))


def test_build_llm_selects_etribe_when_provider_overridden():
    settings = Settings(
        llm_provider="etribe",
        etribe_base_url="http://etribe.test",
        etribe_model="Etribe-LLM",
    )
    llm = assistant.build_llm(_fake_request(), settings)
    assert isinstance(llm, EtribeProvider)


def test_build_llm_default_gemini_path_unchanged():
    # 기본값(gemini)은 기존 경로 그대로 — GitHub/AWS 배포 동작 불변 보호.
    settings = Settings(llm_provider="gemini", gemini_api_key="k")
    llm = assistant.build_llm(_fake_request(), settings)
    assert isinstance(llm, GeminiProvider)


def test_stream_error_message_passes_context_hint_through():
    # 라우터가 컨텍스트 한도 안내를 일반화하지 않고 그대로 사용자에게 표면화한다.
    exc = ContextLengthExceededError("대화가 모델 컨텍스트 한도를 초과했습니다.")
    assert assistant._stream_error_message(exc) == "대화가 모델 컨텍스트 한도를 초과했습니다."
