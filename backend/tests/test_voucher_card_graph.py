"""voucher-card 그래프/등록/fixture 승격 — compile + registry + 공유 백본 회귀 방지.

- 그래프: 8노드(공유 7 + collect_payments)·진입 validate_params·collect_payments 가 run_query 와
  loop_approvals 사이·loop_approvals→END·recursion_limit.
- 공유 백본 무영향: 매출/매입 그래프엔 collect_payments 가 없다(build_voucher_graph 하위호환).
- registry: voucher-card 등록(형제 회귀 금지) + delay_scale.
- fixture: voucher-card-payable 더미 승격(workflow_id·flow_graph·steps.key 가 그래프 노드와 1:1, hidden=False).
"""

from __future__ import annotations

from typing import get_type_hints

import app.agents  # noqa: F401 — import 시 'voucher-card' 등록
from app.agents.voucher_card.graph import (
    VoucherCardState,
    build_voucher_card_graph,
)
from app.agents.voucher_receivable.graph import (
    RECURSION_LIMIT,
    build_voucher_receivable_graph,
)
from app.live.registry import get_spec, get_workflow, list_workflows
from app.services.agent_fixtures import AGENT_FIXTURES

_EXPECTED_NODES = {
    "validate_params",
    "login",
    "user_type",
    "menu_nav",
    "set_query",
    "run_query",
    "collect_payments",
    "loop_approvals",
}


def _graph_nodes(g) -> set[str]:
    return {n for n in g.get_graph().nodes if n not in ("__start__", "__end__")}


# ── 그래프 ────────────────────────────────────────────────────────────────────
def test_graph_compiles_with_expected_nodes_and_entry():
    g = build_voucher_card_graph()
    assert _graph_nodes(g) == _EXPECTED_NODES
    starts = [e.target for e in g.get_graph().edges if e.source == "__start__"]
    assert starts == ["validate_params"]


def test_collect_payments_sits_between_run_query_and_loop():
    g = build_voucher_card_graph()
    edges = {(e.source, e.target) for e in g.get_graph().edges}
    assert ("run_query", "collect_payments") in edges
    assert ("collect_payments", "loop_approvals") in edges
    # run_query 는 loop_approvals 로 **직결되지 않는다**(카드는 collect_payments 를 경유).
    assert ("run_query", "loop_approvals") not in edges


def test_loop_approvals_terminates_at_end():
    g = build_voucher_card_graph()
    targets = {e.target for e in g.get_graph().edges if e.source == "loop_approvals"}
    assert targets == {"__end__"}


def test_recursion_limit_configured():
    g = build_voucher_card_graph()
    assert g.config.get("recursion_limit") == RECURSION_LIMIT == 20


def test_state_declares_card_keys():
    keys = get_type_hints(VoucherCardState)
    # 카드 고유 신규 키 + 공유 상속 키.
    assert {"payment_map", "payment_map_count", "accounting_ym"} <= set(keys)
    assert {"max_rows", "master_rowcount", "processed", "page", "events"} <= set(keys)


# ── 공유 백본 무영향(하위호환) ─────────────────────────────────────────────────
def test_shared_backbone_has_no_collect_payments():
    # 매출(그리고 내수매입)은 build_voucher_graph 를 pre_loop_node 없이 쓰므로 collect_payments 가 없다.
    assert "collect_payments" not in _graph_nodes(build_voucher_receivable_graph())


# ── registry ──────────────────────────────────────────────────────────────────
def test_workflow_registered_without_regressing_others():
    wfs = list_workflows()
    assert "voucher-card" in wfs
    # 형제 회귀 금지.
    for wid in ("voucher-receivable", "voucher-payable", "card-collect", "demo-echo", "trip-domestic"):
        assert wid in wfs


def test_registered_factory_returns_invokable_graph():
    factory = get_workflow("voucher-card")
    assert factory is not None
    assert callable(getattr(factory(), "ainvoke", None))


def test_spec_delay_scale_and_browser():
    spec = get_spec("voucher-card")
    assert spec is not None
    assert spec.needs_browser is True
    assert spec.delay_scale == 0.4
    assert spec.site == "omnisol"


# ── fixture 승격 검증(lockstep) ────────────────────────────────────────────────
def _card_fixture() -> dict:
    return next(a for a in AGENT_FIXTURES if a["id"] == "voucher-card-payable")


def test_fixture_promoted_to_real_workflow():
    fx = _card_fixture()
    assert fx["workflow_id"] == "voucher-card"
    assert fx["group_id"] == "voucher"
    assert fx["name"] == "미지급금 법인카드"
    assert fx["flow_graph"] is not None
    assert fx["hidden"] is False
    # handoff_note 에 상신/참조문서 안전 문구가 있어야 한다.
    assert fx["handoff_note"] and "상신" in fx["handoff_note"] and "참조문서" in fx["handoff_note"]


def test_fixture_step_keys_match_graph_nodes_lockstep():
    fx = _card_fixture()
    assert {s["key"] for s in fx["steps"]} == _EXPECTED_NODES


def test_fixture_phases_cover_steps_in_order():
    fx = _card_fixture()
    phases = [s["phase"] for s in fx["steps"]]
    # 접속×4 → 조회×2 → 수집×1 → 결재×1(연속 구간).
    assert phases == ["접속", "접속", "접속", "접속", "조회", "조회", "수집", "결재"]


def test_sibling_voucher_fixtures_still_present():
    ids = {a["id"] for a in AGENT_FIXTURES}
    assert {"voucher-trade-receivable", "voucher-trade-payable", "voucher-card-payable"} <= ids
