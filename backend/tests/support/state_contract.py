"""에이전트 State TypedDict 계약 검증 유틸.

LangGraph 는 State 에 선언되지 않은 키를 조용히 버린다(silent drop) — 노드 출력 키가
전부 선언됐는지 테스트로 강제한다. 키 수집은 typing.get_type_hints 를 쓴다:
**상속 키를 포함**해 돌려주므로 BaseAgentState 상속 구조에서도 정확하다
(__annotations__ 직접 접근은 자기 클래스 선언분만 보여 상속 키가 빠진다).
"""

from __future__ import annotations

from typing import get_type_hints


def all_declared_keys(state_cls: type) -> set[str]:
    """State TypedDict 의 선언 키 전체(BaseAgentState 등 상속 키 포함)."""
    return set(get_type_hints(state_cls))


def assert_keys_declared(state_cls: type, output: dict) -> None:
    """노드 출력(output)의 모든 키가 state_cls 에 선언됐는지 단언 — 미선언은 조용한 누락."""
    missing = set(output) - all_declared_keys(state_cls)
    assert not missing, f"{state_cls.__name__} 미선언 키(그래프 전달 누락됨): {sorted(missing)}"
