"""에이전트 공통 state 계약 — 러너(app.live)가 모든 에이전트 그래프에 주입하는 키의 단일 정의.

⚠ LangGraph StateGraph 는 State TypedDict 에 **선언되지 않은 키를 조용히 버린다**
(silent drop — 노드가 반환해도 다음 노드로 전달되지 않고, 에러도 없다). 실전 회귀:
pass1_applied_idx 미선언 → save 노드에서 '적용할 행이 없습니다' 실패. 새 에이전트의
State 는 반드시 이 베이스를 상속하고, 노드가 반환하는 키를 전부 선언할 것.
상속 키 검증은 typing.get_type_hints(상속 포함)를 쓴다 — __annotations__ 직접 접근은
자기 클래스 선언분만 보므로 베이스 키가 빠진다(tests/support/state_contract.py 참조).
docs/ARCHITECTURE.md §3 참조.
"""

from __future__ import annotations

from typing import Any, TypedDict


class BaseAgentState(TypedDict, total=False):
    """러너 주입 공통 키(브라우저·이벤트·자격·파라미터·식별자) + 종료 계약(result/error)."""

    page: Any  # Playwright Page(러너 주입)
    browser: Any  # Playwright Browser(러너 주입)
    events: Any  # asyncio.Queue — 진행/대화 이벤트 스트림(러너 주입)
    userid: str | None
    password: str | None
    params: dict
    owner: str | None  # HITL 소유자(세션 사용자 id) — 채널 오픈 시 바인딩(러너 주입)
    run_id: str | None  # 세션/런 id — HITL 런바인딩(러너 주입)
    result: str | dict  # 완료 결과(→ succeeded) — 러너가 result 프레임으로 흘리고 영속
    error: str  # 실패 사유(→ failed)
