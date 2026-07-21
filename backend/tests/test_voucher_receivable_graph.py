"""voucher-receivable 그래프/등록/fixture 승격 단위테스트 — compile + registry + 회귀 방지.

- 그래프: 노드 집합·진입점(validate_params)·선형 종료(loop_approvals→END)·recursion_limit.
- registry: voucher-receivable 등록(demo-echo·card-collect·trip-domestic 회귀 금지) + delay_scale.
- menu_nav 파라미터화: 기본 EXPENSE_CARD 유지 + VOUCHER_RECEIVABLE 주입 동작(하위호환).
- fixture: voucher-trade-receivable 더미 승격(workflow_id·flow_graph·steps.key 가 그래프 노드와 1:1, hidden).
"""

from __future__ import annotations

import asyncio

import pytest

import app.agents  # noqa: F401 — import 시 'voucher-receivable' 등록
from app.agents.common.nodes import make_menu_nav_node
from app.agents.voucher_receivable.graph import (
    RECURSION_LIMIT,
    build_voucher_receivable_graph,
)
from app.live.registry import get_spec, get_workflow, list_workflows
from app.services.agent_fixtures import AGENT_FIXTURES
from nbkit.omnisol.menu_schemas import EXPENSE_CARD, VOUCHER_RECEIVABLE

_EXPECTED_NODES = {
    "validate_params",
    "login",
    "user_type",
    "menu_nav",
    "set_query",
    "run_query",
    "loop_approvals",
}


def _graph_nodes(g) -> set[str]:
    return {n for n in g.get_graph().nodes if n not in ("__start__", "__end__")}


# ── 그래프 ────────────────────────────────────────────────────────────────────
def test_graph_compiles_with_expected_nodes_and_entry():
    g = build_voucher_receivable_graph()
    assert _graph_nodes(g) == _EXPECTED_NODES
    starts = [e.target for e in g.get_graph().edges if e.source == "__start__"]
    assert starts == ["validate_params"]


def test_loop_approvals_terminates_at_end():
    g = build_voucher_receivable_graph()
    targets = {e.target for e in g.get_graph().edges if e.source == "loop_approvals"}
    assert targets == {"__end__"}


def test_recursion_limit_configured():
    g = build_voucher_receivable_graph()
    assert g.config.get("recursion_limit") == RECURSION_LIMIT == 20


def test_graph_is_recompilable():
    assert build_voucher_receivable_graph() is not None


# ── registry ──────────────────────────────────────────────────────────────────
def test_workflow_registered_without_regressing_others():
    wfs = list_workflows()
    assert "voucher-receivable" in wfs
    # 회귀 금지.
    assert "card-collect" in wfs and "demo-echo" in wfs and "trip-domestic" in wfs


def test_registered_factory_returns_invokable_graph():
    factory = get_workflow("voucher-receivable")
    assert factory is not None
    graph = factory()
    assert callable(getattr(graph, "ainvoke", None))


def test_spec_delay_scale_and_browser():
    spec = get_spec("voucher-receivable")
    assert spec is not None
    assert spec.needs_browser is True
    assert spec.delay_scale == 0.4
    assert spec.site == "omnisol"


# ── menu_nav 파라미터화(하위호환) ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_menu_nav_defaults_to_expense_card(monkeypatch):
    seen: dict = {}

    async def _capture(page, schema, base, *, emit=None):
        seen["schema"] = schema

    import app.agents.common.nodes as common_nodes

    monkeypatch.setattr(common_nodes, "navigate_schema", _capture)
    node = make_menu_nav_node()  # 무인자 = 기존 호출부(EXPENSE_CARD 기본).
    out = await node({"events": asyncio.Queue(), "page": object()})
    assert out == {} and seen["schema"] is EXPENSE_CARD


@pytest.mark.asyncio
async def test_menu_nav_accepts_voucher_schema(monkeypatch):
    seen: dict = {}

    async def _capture(page, schema, base, *, emit=None):
        seen["schema"] = schema

    import app.agents.common.nodes as common_nodes

    monkeypatch.setattr(common_nodes, "navigate_schema", _capture)
    node = make_menu_nav_node(VOUCHER_RECEIVABLE)
    out = await node({"events": asyncio.Queue(), "page": object()})
    assert out == {} and seen["schema"] is VOUCHER_RECEIVABLE


# ── fixture 승격 검증 ─────────────────────────────────────────────────────────
def _voucher_fixture() -> dict:
    return next(a for a in AGENT_FIXTURES if a["id"] == "voucher-trade-receivable")


def test_fixture_promoted_to_real_workflow():
    fx = _voucher_fixture()
    assert fx["workflow_id"] == "voucher-receivable"
    assert fx["group_id"] == "voucher"
    assert fx["flow_graph"] is not None
    assert fx["handoff_note"] and "상신" in fx["handoff_note"]
    # 완전 공개(사용자 결정 2026-07-21) — 목록 노출 + 실행 허용. 배치(allow_batch)는 코드 게이트,
    # 실행 자체는 hidden 아님. (라이브 단건 스모크 PASS 2026-07-21.)
    assert fx["hidden"] is False


def test_fixture_step_keys_match_graph_nodes():
    fx = _voucher_fixture()
    step_keys = {s["key"] for s in fx["steps"]}
    assert step_keys == _EXPECTED_NODES


def test_fixture_phases_cover_steps_in_order():
    fx = _voucher_fixture()
    phases = [s["phase"] for s in fx["steps"]]
    assert phases == ["접속", "접속", "접속", "접속", "조회", "조회", "결재"]


def test_other_voucher_dummies_still_present():
    ids = {a["id"] for a in AGENT_FIXTURES}
    # 형제 더미는 그대로(회귀 금지).
    assert {"voucher-trade-payable", "voucher-card-payable"} <= ids
