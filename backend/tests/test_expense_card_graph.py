"""expense_card 그래프/등록 단위테스트 — compile + registry 등록 + demo-echo 회귀 방지."""

from __future__ import annotations

import app.agents  # noqa: F401 — import 시 'expense-card-chat' 등록
from app.agents.expense_card.graph import build_expense_card_chat_graph
from app.live.registry import get_workflow, list_workflows

_EXPECTED_NODES = {
    "login",
    "user_type",
    "menu_nav",
    "set_gubun",
    "add_row",
    "open_evdn",
    "select_evdn",
    "chat_form",
}


def test_workflow_registered_without_regressing_demo_echo():
    wfs = list_workflows()
    assert "expense-card-chat" in wfs
    assert "demo-echo" in wfs  # P2 더미 회귀 금지


def test_registered_factory_returns_invokable_graph():
    factory = get_workflow("expense-card-chat")
    assert factory is not None
    graph = factory()
    assert callable(getattr(graph, "ainvoke", None))


def test_graph_compiles_with_expected_node_chain():
    g = build_expense_card_chat_graph()
    node_ids = set(g.get_graph().nodes.keys())
    assert _EXPECTED_NODES <= node_ids
    # 진입점은 login.
    assert "login" in node_ids


def test_graph_is_recompilable():
    # 재컴파일이 예외 없이 되는지(팩토리 재사용 안전성 확인).
    assert build_expense_card_chat_graph() is not None
