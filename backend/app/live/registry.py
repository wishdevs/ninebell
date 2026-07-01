"""워크플로우 레지스트리 — agent_id ↔ 그래프 팩토리.

P3 가 `register_workflow("expense-card-chat", factory)` 로 실제 워크플로우를 등록한다.
factory 는 컴파일된 LangGraph(또는 `.ainvoke(state)` 를 가진 객체)를 반환하며, 러너가
state(page/events/creds/params)를 주입해 실행한다. P2 는 `demo-echo` 를 기본 등록한다.
"""

from __future__ import annotations

from typing import Any, Callable

# agent_id → 그래프 팩토리(호출 시 컴파일된 그래프 반환).
GraphFactory = Callable[[], Any]

_WORKFLOWS: dict[str, GraphFactory] = {}


def register_workflow(agent_id: str, factory: GraphFactory) -> None:
    """워크플로우 등록(또는 교체). factory() 는 컴파일된 LangGraph 를 반환해야 한다."""
    _WORKFLOWS[agent_id] = factory


def get_workflow(agent_id: str) -> GraphFactory | None:
    return _WORKFLOWS.get(agent_id)


def list_workflows() -> list[str]:
    return sorted(_WORKFLOWS)


# ── 기본 등록(P2 더미) ────────────────────────────────────────────────────
def _register_builtin() -> None:
    from .demo_echo import build_demo_echo_graph

    # 컴파일된 그래프는 stateless·재사용 가능 → 1회 컴파일 후 팩토리는 그걸 반환.
    _graph = build_demo_echo_graph()
    register_workflow("demo-echo", lambda: _graph)


_register_builtin()
