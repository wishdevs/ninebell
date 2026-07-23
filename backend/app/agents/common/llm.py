"""LLM 프로바이더 디스패처 — 에이전트 직접 호출 경로의 gemini/etribe 분기(단일 진입점).

호출부(expense_card.chat_form / card_collect.recommend / services.card_learning)는 이 모듈의
`chat_decide`/`generate_text` 만 부르고 프로바이더를 모른다. `settings.llm_provider` 가
'etribe' 면 사내 Etribe-LLM(OpenAI 호환, 온프렘 — 데이터가 사외로 안 나감), 그 외(기본
'gemini')는 기존 Gemini 경로 — **기본값에서 동작 불변**(GitHub/AWS 배포 보호).

settings 는 호출부가 이미 들고 있으면 주입(테스트에서 SimpleNamespace 로 대체 용이),
없으면 get_settings() 로 스스로 해소한다 — 호출부가 키/모델/베이스를 꺼내 넘길 필요 없음.
"""

from __future__ import annotations

from typing import Any

from app.agents.common.etribe import etribe_chat_decide, etribe_generate_text
from app.agents.common.gemini import gemini_chat_decide, gemini_generate_text
from app.config import get_settings
from app.core.llm_runtime import effective_llm_provider


def _is_etribe(settings: Any) -> bool:
    """etribe 프로바이더 여부 — 런타임 오버라이드 우선(effective_llm_provider).

    오버라이드 미설정이면 기존과 동일: llm_provider 미보유(테스트 더미 settings 등)는
    gemini 취급.
    """
    return effective_llm_provider(settings) == "etribe"


def llm_ready(settings: Any) -> bool:
    """LLM 호출 가능 여부 — etribe 는 인증 없음(항상 가능), gemini 는 API 키 필요.

    호출부의 기존 `settings.gemini_api_key` 게이트 대체용 — gemini 경로에선 판정 동일.
    """
    if _is_etribe(settings):
        return True
    return bool((getattr(settings, "gemini_api_key", "") or "").strip())


def llm_model_name(settings: Any) -> str:
    """활성 프로바이더의 모델명 — AI 적요 캐시(CardAiNote.model) 등 기록용."""
    return settings.etribe_model if _is_etribe(settings) else settings.gemini_model


async def chat_decide(
    http: Any,
    *,
    system: str,
    history: str,
    context: dict,
    shot_b64: str | None,
    tools: list[dict],
    settings: Any | None = None,
) -> tuple[str | None, dict]:
    """function-calling 한 턴 — 활성 프로바이더로 `tools` 중 1개 강제 호출, (name, args) 반환.

    반환 계약은 gemini_chat_decide 와 동일(도구 없으면 (None, {}), 일시 오류 재시도 후 raise).
    """
    s = settings if settings is not None else get_settings()
    if _is_etribe(s):
        return await etribe_chat_decide(
            http, s.etribe_model, s.etribe_base_url, system, history, context, shot_b64, tools
        )
    return await gemini_chat_decide(
        http,
        # strip: 교체 전 card_learning 이 하던 정리 보존 — .env 의 따옴표/공백 딸린 키가
        # 헤더로 그대로 나가 무음 실패(휴리스틱 폴백)하는 회귀 방지. llm_ready 판정과 일치.
        (s.gemini_api_key or "").strip(),
        s.gemini_model,
        s.gemini_base_url,
        system,
        history,
        context,
        shot_b64,
        tools,
    )


async def generate_text(
    http: Any,
    *,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_output_tokens: int = 256,
    thinking_budget: int | None = None,
    settings: Any | None = None,
) -> str | None:
    """단발 텍스트 생성 — 활성 프로바이더로 순수 텍스트 1개(없으면 None).

    thinking_budget 은 gemini 전용 파라미터 — etribe 는 요청에서 thinking 자체를 끄므로 무시.
    """
    s = settings if settings is not None else get_settings()
    if _is_etribe(s):
        return await etribe_generate_text(
            http,
            s.etribe_model,
            s.etribe_base_url,
            system=system,
            user=user,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
    return await gemini_generate_text(
        http,
        (s.gemini_api_key or "").strip(),  # chat_decide 와 동일 — llm_ready 판정과 wire 일치.
        s.gemini_model,
        s.gemini_base_url,
        system=system,
        user=user,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        thinking_budget=thinking_budget,
    )
