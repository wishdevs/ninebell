"""LLM 프로바이더 seam — 라우터/스키마는 이 인터페이스에만 의존한다.

오늘은 GeminiProvider(외부). 나중에 온프렘 프로바이더로 교체해도 라우터를 건드리지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ChatChunk:
    delta: str
    done: bool = False
    finish_reason: str | None = None
    # 모델이 의도를 함수호출로 결정했을 때: {"name": str, "args": dict}
    tool_call: dict | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 8192,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[ChatChunk]: ...

    async def aclose(self) -> None: ...
