"""Etribe-LLM 스트리밍 프로바이더 — 온프렘 OpenAI 호환 /v1/chat/completions 를 직접 파싱.

사내 Etribe-LLM 서버는 인증이 없고(Bearer 아무 값) "stream": true 로 SSE
chat.completion.chunk 를 흘린다. thinking 이 기본 ON 이라 사고 과정이 별도
`reasoning_content` 델타 채널로 오므로(응답이 아님) 건너뛴다 — gemini 의 thought
파트 스킵과 동치. 툴콜은 OpenAI 표준이라 arguments 가 문자열 조각으로 나뉘어 오며,
조각을 누적해 완성 시점에 GeminiProvider 와 같은 모양({"name", "args"})으로 1회 방출한다.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import httpx

from app.llm.base import ChatChunk, ChatMessage

# 스트림 전체 벽시계 상한 — 멈춘/무한 업스트림이 연결을 무한 점유하지 못하게 한다(gemini 와 동일).
_STREAM_TIMEOUT_S = 120

# 컨텍스트 한도 초과(HTTP 400 code=context_length_exceeded) 사용자 안내 — API 가이드가
# '요약 후 새 세션으로 이어가기(handoff)'를 권고하므로 그 힌트를 메시지에 포함한다.
_CONTEXT_LIMIT_MESSAGE = (
    "대화가 모델 컨텍스트 한도를 초과했습니다. "
    "지금까지의 내용을 요약해 새 대화를 시작해 주세요."
)


class ContextLengthExceededError(RuntimeError):
    """Etribe-LLM 컨텍스트 한도 초과 — 메시지가 그대로 사용자에게 표면화되어도 안전하다."""


class EtribeProvider:
    name = "etribe"

    def __init__(self, client: httpx.AsyncClient, *, model: str, base_url: str):
        self._http = client
        self._model = model
        self._base = base_url.rstrip("/")

    def _build_body(self, messages, system, temperature, max_output_tokens, tools) -> dict:
        # 시스템 프롬프트: 인자 system + 히스토리의 system 롤을 합쳐 맨 앞 system 메시지 1개로.
        sys_text = "\n\n".join(
            s for s in ([system] + [m.content for m in messages if m.role == "system"]) if s
        )
        oai_messages: list[dict] = []
        if sys_text:
            oai_messages.append({"role": "system", "content": sys_text})
        oai_messages.extend(
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        )
        body: dict = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "stream": True,
        }
        if tools:
            # 라우터의 함수 선언({"name","description","parameters"})을 OpenAI tools 로 감싼다.
            body["tools"] = [{"type": "function", "function": t} for t in tools]
            body["tool_choice"] = "auto"
        return body

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system=None,
        temperature=0.7,
        max_output_tokens=8192,
        tools=None,
    ) -> AsyncIterator[ChatChunk]:
        url = f"{self._base}/v1/chat/completions"
        body = self._build_body(messages, system, temperature, max_output_tokens, tools)
        # 인증 없음 — 키는 아무 값이나 허용(가이드). OpenAI 호환 형식만 맞춘다.
        headers = {"authorization": "Bearer none", "content-type": "application/json"}
        done_sent = False  # finish_reason 으로 이미 done 을 냈으면 마지막 보강 done 을 생략.
        # OpenAI 스트리밍 툴콜: arguments 가 문자열 조각으로 나뉘어 온다 — index 별 누적 버퍼.
        pending_calls: dict[int, dict] = {}

        def _drain_tool_calls() -> list[ChatChunk]:
            """누적 완료된 툴콜을 GeminiProvider 와 같은 모양({"name","args"})으로 1회씩 변환."""
            chunks: list[ChatChunk] = []
            for idx in sorted(pending_calls):
                call = pending_calls[idx]
                try:
                    args = json.loads(call["arguments"]) if call["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                chunks.append(ChatChunk(delta="", tool_call={"name": call["name"], "args": args}))
            pending_calls.clear()
            return chunks

        try:
            async with asyncio.timeout(_STREAM_TIMEOUT_S):
                async with self._http.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code >= 400:
                        # 스트림 응답은 본문을 읽어야 코드 검사가 가능하다.
                        raw = await resp.aread()
                        if resp.status_code == 400 and b"context_length_exceeded" in raw:
                            raise ContextLengthExceededError(_CONTEXT_LIMIT_MESSAGE)
                        resp.raise_for_status()  # 그 외 비 2xx 는 gemini 관례 미러(HTTPStatusError)
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if payload == "[DONE]":
                            break
                        obj = json.loads(payload)
                        choice = (obj.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        # thinking 기본 ON — 사고 과정은 reasoning_content 채널로 온다(응답 아님) → 무시.
                        txt = delta.get("content")
                        if txt:
                            yield ChatChunk(delta=txt)
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index") or 0
                            slot = pending_calls.setdefault(idx, {"name": None, "arguments": ""})
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            slot["arguments"] += fn.get("arguments") or ""
                        finish = choice.get("finish_reason")
                        if finish and not done_sent:
                            # 툴콜 완성 신호 — done 프레임보다 먼저 방출(gemini 와 동일한 순서).
                            for c in _drain_tool_calls():
                                yield c
                            done_sent = True
                            yield ChatChunk(delta="", done=True, finish_reason=finish)
        except TimeoutError:
            yield ChatChunk(delta="", done=True, finish_reason="timeout")
            return
        if not done_sent:
            # finish_reason 없이 [DONE] 만 온 경우 — 잔여 툴콜을 비우고 done 을 보강한다.
            for c in _drain_tool_calls():
                yield c
            yield ChatChunk(delta="", done=True)

    async def aclose(self) -> None:
        return None
