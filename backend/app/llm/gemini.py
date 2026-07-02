"""Gemini 스트리밍 프로바이더 — :streamGenerateContent?alt=sse 를 직접 파싱.

functionDeclarations + toolConfig mode=AUTO 로 모델이 의도에 따라 자율적으로 함수를
호출하게 한다. gemini-2.5-flash 는 사고 과정을 `"thought": true` 파트로 흘리므로
텍스트/함수호출 파싱에서 이를 건너뛴다.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import httpx

from app.llm.base import ChatChunk, ChatMessage

_ROLE = {"user": "user", "assistant": "model"}  # "system" 은 별도 처리

# 스트림 전체 벽시계 상한 — 멈춘/무한 업스트림이 연결을 무한 점유하지 못하게 한다.
_STREAM_TIMEOUT_S = 120


class GeminiProvider:
    name = "gemini"

    def __init__(self, client: httpx.AsyncClient, *, api_key: str, model: str, base_url: str):
        self._http = client
        self._key = api_key
        self._model = model
        self._base = base_url.rstrip("/")

    def _build_body(self, messages, system, temperature, max_output_tokens, tools) -> dict:
        contents = [
            {"role": _ROLE.get(m.role, "user"), "parts": [{"text": m.content}]}
            for m in messages
            if m.role != "system"
        ]
        sys_text = "\n\n".join(
            s for s in ([system] + [m.content for m in messages if m.role == "system"]) if s
        )
        body: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        if sys_text:
            body["system_instruction"] = {"parts": [{"text": sys_text}]}
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
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
        url = f"{self._base}/models/{self._model}:streamGenerateContent"
        body = self._build_body(messages, system, temperature, max_output_tokens, tools)
        headers = {"x-goog-api-key": self._key, "content-type": "application/json"}
        done_sent = False  # finishReason 으로 이미 done 을 냈으면 마지막 보강 done 을 생략(중복 [DONE] 방지).
        try:
            async with asyncio.timeout(_STREAM_TIMEOUT_S):
                async with self._http.stream(
                    "POST", url, params={"alt": "sse"}, headers=headers, json=body
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if payload == "[DONE]":
                            break
                        obj = json.loads(payload)
                        cand = (obj.get("candidates") or [{}])[0]
                        parts = (cand.get("content") or {}).get("parts") or []
                        for p in parts:
                            # gemini-2.5-flash 는 사고 과정을 thought 파트로 흘린다 — 응답이 아니므로 무시.
                            if p.get("thought"):
                                continue
                            txt = p.get("text")
                            if txt:
                                yield ChatChunk(delta=txt)
                            fc = p.get("functionCall")
                            if fc:
                                yield ChatChunk(
                                    delta="",
                                    tool_call={
                                        "name": fc.get("name"),
                                        "args": fc.get("args") or {},
                                    },
                                )
                        if cand.get("finishReason"):
                            done_sent = True
                            yield ChatChunk(
                                delta="", done=True, finish_reason=cand["finishReason"]
                            )
        except TimeoutError:
            yield ChatChunk(delta="", done=True, finish_reason="timeout")
            return
        if not done_sent:
            yield ChatChunk(delta="", done=True)

    async def aclose(self) -> None:
        return None
