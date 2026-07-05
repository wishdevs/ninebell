"""워크플로우 레지스트리 — agent_id ↔ 그래프 팩토리 + 실행 메타(WorkflowSpec).

`register_workflow("expense-card-chat", factory, delay_scale=…)` 로 실제 워크플로우를 등록한다.
factory 는 컴파일된 LangGraph(또는 `.ainvoke(state)` 를 가진 객체)를 반환하며, 러너가
state(page/events/creds/params)를 주입해 실행한다.

WorkflowSpec 은 **에이전트별 실행 노브의 단일소스**다(코드와 함께 버전) — DB `Agent` 행은
노출/권한 전용. 노브: needs_browser(순수 LLM 에이전트는 False → 브라우저 경로 생략),
delay_scale(라이브 검증된 에이전트만 대기 축소), site/login_form_selector(웜 세션 캐시 스코프).
자세한 규칙은 docs/ARCHITECTURE.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# agent_id → 그래프 팩토리(호출 시 컴파일된 그래프 반환).
GraphFactory = Callable[[], Any]


@dataclass(frozen=True)
class WorkflowSpec:
    """워크플로우 실행 메타. 기본값은 옴니솔 브라우저 에이전트(현 주류)에 맞춰져 있다."""

    agent_id: str
    factory: GraphFactory
    needs_browser: bool = True  # False = 브라우저·스크린캐스트·세션캐시 전부 생략(순수 API/LLM)
    delay_scale: float | None = None  # 대기 배율(None=1.0). env CARD_DELAY_SCALE 이 항상 우선.
    site: str = "omnisol"  # 웜 세션 캐시 네임스페이스((site, userid) 키)
    login_form_selector: str | None = "#userid"  # 웜 판정 셀렉터. None = 캐시 비활성.


_WORKFLOWS: dict[str, WorkflowSpec] = {}


def register_workflow(
    agent_id: str,
    factory: GraphFactory,
    *,
    needs_browser: bool = True,
    delay_scale: float | None = None,
    site: str = "omnisol",
    login_form_selector: str | None = "#userid",
) -> None:
    """워크플로우 등록(또는 교체). factory() 는 컴파일된 LangGraph 를 반환해야 한다.

    기존 `register_workflow(id, factory)` 2-인자 호출은 그대로 유효(kwargs 전부 기본값).
    """
    _WORKFLOWS[agent_id] = WorkflowSpec(
        agent_id=agent_id,
        factory=factory,
        needs_browser=needs_browser,
        delay_scale=delay_scale,
        site=site,
        login_form_selector=login_form_selector,
    )


def get_spec(agent_id: str) -> WorkflowSpec | None:
    """실행 메타 포함 스펙 조회 — 러너/라우터가 노브를 여기서 읽는다."""
    return _WORKFLOWS.get(agent_id)


def get_workflow(agent_id: str) -> GraphFactory | None:
    """팩토리만 필요한 호출부용 하위호환 표면."""
    spec = _WORKFLOWS.get(agent_id)
    return spec.factory if spec is not None else None


def list_workflows() -> list[str]:
    return sorted(_WORKFLOWS)


# ── 기본 등록(P2 더미) ────────────────────────────────────────────────────
def _register_builtin() -> None:
    from .demo_echo import build_demo_echo_graph

    # 컴파일된 그래프는 stateless·재사용 가능 → 1회 컴파일 후 팩토리는 그걸 반환.
    _graph = build_demo_echo_graph()
    register_workflow("demo-echo", lambda: _graph)


_register_builtin()
