"""voucher-by-type 그래프/등록/fixture 단위테스트 — compile + registry + 병합 회귀 방지.

외상매출금/외상매입금 병합(2026-08-20): 그래프는 build_voucher_by_type_graph 하나이고
전표유형은 실행 전 폼 선택(state.docu_types)이 우선한다.
- 그래프: 노드 집합·진입점(validate_params)·선형 종료(loop_approvals→END)·recursion_limit.
- registry: voucher-by-type 등록 + 구 워크플로우(voucher-receivable/voucher-payable) 제거 확인.
- menu_nav 파라미터화: 기본 EXPENSE_CARD 유지 + VOUCHER_RECEIVABLE 주입 동작(하위호환).
- fixture: voucher-by-type 단일 픽스처(workflow_id·flow_graph·steps.key 가 그래프 노드와 1:1).
"""

from __future__ import annotations

import asyncio

import pytest

import app.agents  # noqa: F401 — import 시 'voucher-by-type' 등록
from app.agents.common.nodes import make_menu_nav_node
from app.agents.voucher_receivable.graph import (
    RECURSION_LIMIT,
    build_voucher_by_type_graph,
)
from app.agents.voucher_receivable.steps import DOCU_TYPE_CHOICES
from app.live.registry import get_spec, get_workflow, list_workflows
from app.services.agent_fixtures import AGENT_FIXTURES
from nbkit.omnisol.menu_schemas import EXPENSE_CARD, VOUCHER_RECEIVABLE

# 공유 백본 코어 노드 집합(건별 순회 원형 — 현재 카드 계열이 사용).
_EXPECTED_NODES = {
    "validate_params",
    "login",
    "user_type",
    "menu_nav",
    "set_query",
    "run_query",
    "loop_approvals",
}
# 배치 결재는 하위 건수 파악 노드가 하나 더 붙는다 — 매출(2026-07-27)·매입(2026-08-07 확대).
_EXPECTED_NODES_BATCH = _EXPECTED_NODES | {"count_details"}


def _graph_nodes(g) -> set[str]:
    return {n for n in g.get_graph().nodes if n not in ("__start__", "__end__")}


# ── 그래프 ────────────────────────────────────────────────────────────────────
def test_graph_compiles_with_expected_nodes_and_entry():
    g = build_voucher_by_type_graph()
    assert _graph_nodes(g) == _EXPECTED_NODES_BATCH
    starts = [e.target for e in g.get_graph().edges if e.source == "__start__"]
    assert starts == ["validate_params"]


def test_loop_approvals_terminates_at_end():
    g = build_voucher_by_type_graph()
    targets = {e.target for e in g.get_graph().edges if e.source == "loop_approvals"}
    assert targets == {"__end__"}


def test_recursion_limit_configured():
    g = build_voucher_by_type_graph()
    assert g.config.get("recursion_limit") == RECURSION_LIMIT == 20


def test_graph_is_recompilable():
    assert build_voucher_by_type_graph() is not None


def test_docu_type_catalog_and_default():
    """확장(2026-08-20): 허용셋 = 실측 카탈로그 62종(중복 없음, ERP 는 SYSDEF_NM 라벨 매칭),
    빌드 기본값 = 병합 전 두 에이전트의 합집합 3종(미지정 실행이 62종 전체로 돌지 않게)."""
    from app.agents.voucher_receivable.docu_types import (
        DOCU_TYPE_CATALOG,
        DOCU_TYPE_DEFAULT,
    )

    assert len(DOCU_TYPE_CATALOG) == 62
    assert len(DOCU_TYPE_CHOICES) == 62 == len(set(DOCU_TYPE_CHOICES))
    assert DOCU_TYPE_CHOICES == tuple(label for _, label in DOCU_TYPE_CATALOG)
    assert DOCU_TYPE_DEFAULT == ("국내매출", "해외매출", "내수구매")
    assert set(DOCU_TYPE_DEFAULT) <= set(DOCU_TYPE_CHOICES)
    # 코드/라벨 전부 비어있지 않은 문자열(아티팩트 재생성 회귀 방지).
    assert all(c.strip() and l.strip() for c, l in DOCU_TYPE_CATALOG)


def test_build_uses_default_not_full_catalog(monkeypatch):
    """빌드 인자 = DOCU_TYPE_DEFAULT(3종) — 62종 전체가 기본 조회 조건이 되는 사고 방지."""
    import app.agents.voucher_receivable.graph as graph_mod
    from app.agents.voucher_receivable.docu_types import DOCU_TYPE_DEFAULT

    seen: dict = {}
    real = graph_mod.build_voucher_graph

    def _capture(docu_types, **kw):
        seen["docu_types"] = docu_types
        return real(docu_types, **kw)

    monkeypatch.setattr(graph_mod, "build_voucher_graph", _capture)
    assert graph_mod.build_voucher_by_type_graph() is not None
    assert seen["docu_types"] == DOCU_TYPE_DEFAULT == ("국내매출", "해외매출", "내수구매")


# ── registry ──────────────────────────────────────────────────────────────────
def test_workflow_registered_without_regressing_others():
    wfs = list_workflows()
    assert "voucher-by-type" in wfs
    # 병합으로 구 워크플로우 id 는 제거됐다(잔존 시 프론트 진입점이 두 갈래가 되는 회귀).
    assert "voucher-receivable" not in wfs and "voucher-payable" not in wfs
    # 회귀 금지.
    assert "card-collect" in wfs and "demo-echo" in wfs and "trip-domestic" in wfs


def test_registered_factory_returns_invokable_graph():
    factory = get_workflow("voucher-by-type")
    assert factory is not None
    graph = factory()
    assert callable(getattr(graph, "ainvoke", None))


def test_spec_delay_scale_and_browser():
    spec = get_spec("voucher-by-type")
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


# ── fixture(병합 단일 픽스처) ─────────────────────────────────────────────────
def _voucher_fixture() -> dict:
    return next(a for a in AGENT_FIXTURES if a["id"] == "voucher-by-type")


def test_fixture_merged_to_single_agent():
    fx = _voucher_fixture()
    assert fx["workflow_id"] == "voucher-by-type"
    assert fx["group_id"] == "voucher"
    assert fx["name"] == "유형별 전표조회 승인"
    assert fx["flow_graph"] is not None
    assert fx["handoff_note"] and "상신" in fx["handoff_note"]
    assert fx["hidden"] is False


def test_fixture_step_keys_match_graph_nodes():
    fx = _voucher_fixture()
    step_keys = {s["key"] for s in fx["steps"]}
    assert step_keys == _EXPECTED_NODES_BATCH


def test_fixture_phases_cover_steps_in_order():
    fx = _voucher_fixture()
    phases = [s["phase"] for s in fx["steps"]]
    assert phases == ["접속", "접속", "접속", "접속", "조회", "조회", "조회", "결재"]


def test_old_split_fixtures_removed_and_card_kept():
    ids = {a["id"] for a in AGENT_FIXTURES}
    # 병합으로 구 두 픽스처는 제거됐다 — 잔존 시 시드가 구 에이전트를 되살린다.
    assert "voucher-trade-receivable" not in ids and "voucher-trade-payable" not in ids
    # 카드는 별도 유지(회귀 금지).
    assert "voucher-card-payable" in ids
