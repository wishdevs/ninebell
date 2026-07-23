"""LLM 프로바이더 런타임 오버라이드 — 프로세스 메모리 전역(로컬 dev 전용).

lru_cache 된 get_settings() 와 무관하게 동작한다: 오버라이드는 이 모듈 전역에만 저장되고,
effective_llm_provider() 가 모든 read-site(에이전트 디스패처 app.agents.common.llm 와
/assistant 의 build_llm)의 단일 판정 지점이다. 오버라이드 미설정이면
settings.llm_provider(env) 그대로 — **기본값에서 기존 동작 불변**(서버 배포 보호).
프로세스 재시작 시 오버라이드는 사라지고 env 기본으로 복귀한다(로컬 dev 용도로 의도된
동작 — routers/dev_llm 참조).
"""

from __future__ import annotations

from typing import Any

_VALID_PROVIDERS = ("gemini", "etribe")

# 프로세스 전역 오버라이드(None=미설정 → env 기본). 단일 워커 전제 — 멀티 프로세스 공유 없음.
_override: str | None = None


def effective_llm_provider(settings: Any) -> str:
    """활성 LLM 프로바이더 — 오버라이드 우선, 없으면 settings.llm_provider.

    getattr 폴백('gemini')은 llm_provider 속성이 없는 테스트 더미 settings(SimpleNamespace
    등) 호환 유지용 — 기존 _is_etribe 의 폴백 시맨틱과 동일.
    """
    if _override is not None:
        return _override
    return getattr(settings, "llm_provider", "gemini")


def set_llm_provider_override(p: str | None) -> None:
    """오버라이드 설정(None 이면 해제 → env 기본으로 복귀). 미지 값은 ValueError.

    검증은 config 의 llm_provider 검증기와 같은 이유 — 오타가 조용히 gemini 폴백되면
    온프렘 데이터가 무음으로 사외에 나갈 수 있어 즉시 실패시킨다.
    """
    global _override
    if p is not None and p not in _VALID_PROVIDERS:
        raise ValueError(f"LLM 프로바이더는 {_VALID_PROVIDERS} 만 허용합니다(입력: {p!r})")
    _override = p


def llm_provider_source() -> str:
    """현재 판정 출처 — 오버라이드 활성이면 'override', 아니면 'env'."""
    return "override" if _override is not None else "env"
