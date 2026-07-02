"""AI 어시스턴트 채팅 요청 스키마 — POST /assistant/chat 본문.

내부 요청 본문이라 camelCase 변환이 필요 없어 평범한 BaseModel 을 쓴다.
메시지 수(≤50)·개별 길이(≤8000)를 제한해 프롬프트 폭주/남용을 막는다.
context 는 프론트가 만든 {agents, runs} 스냅샷이지만 형태를 강제하진 않고, 시스템 프롬프트에
그대로 직렬화되므로 직렬화 길이만 상한(과대 페이로드로 인한 비용/지연 폭주 방지).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, field_validator

_CONTEXT_MAX_JSON_CHARS = 20_000


class MessageIn(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    messages: list[MessageIn] = Field(min_length=1, max_length=50)
    system: str | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_output_tokens: int = Field(default=8192, ge=1, le=65000)
    context: dict | None = None

    @field_validator("context")
    @classmethod
    def _bound_context_size(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        size = len(json.dumps(v, ensure_ascii=False))
        if size > _CONTEXT_MAX_JSON_CHARS:
            raise ValueError(f"context 가 너무 큽니다({size}자, 최대 {_CONTEXT_MAX_JSON_CHARS}자).")
        return v
