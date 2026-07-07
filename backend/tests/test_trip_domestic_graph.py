"""trip-domestic 그래프/등록/fixture 승격 단위테스트 — compile + registry + 회귀 방지.

- 그래프: 노드 집합·진입점(validate_params)·저장 재시도 분기(save_doc→menu_nav/END)·recursion_limit.
- registry: trip-domestic 등록(demo-echo·card-collect 회귀 금지).
- fixture: 더미 승격(workflow_id·flow_graph·steps.key 가 그래프 노드와 1:1).
"""

from __future__ import annotations

import app.agents  # noqa: F401 — import 시 'trip-domestic' 등록
from app.agents.trip_domestic.graph import (
    RECURSION_LIMIT,
    TRIP_GUBUN_LABEL,
    build_trip_domestic_graph,
)
from app.live.registry import get_workflow, list_workflows
from app.services.agent_fixtures import AGENT_FIXTURES

_EXPECTED_NODES = {
    "validate_params",
    "login",
    "user_type",
    "menu_nav",
    "set_gubun",
    "add_row",
    "set_acct_date",
    "fill_rows",
    "save_doc",
}


def _graph_nodes(g) -> set[str]:
    return {n for n in g.get_graph().nodes if n not in ("__start__", "__end__")}


def test_workflow_registered_without_regressing_others():
    wfs = list_workflows()
    assert "trip-domestic" in wfs
    assert "card-collect" in wfs and "demo-echo" in wfs  # 회귀 금지


def test_registered_factory_returns_invokable_graph():
    factory = get_workflow("trip-domestic")
    assert factory is not None
    graph = factory()
    assert callable(getattr(graph, "ainvoke", None))


def test_graph_compiles_with_expected_nodes_and_entry():
    g = build_trip_domestic_graph()
    assert _graph_nodes(g) == _EXPECTED_NODES
    # 진입점은 validate_params(브라우저 앞 검증).
    starts = [e.target for e in g.get_graph().edges if e.source == "__start__"]
    assert starts == ["validate_params"]


def test_save_doc_has_retry_branch_to_menu_nav_and_end():
    g = build_trip_domestic_graph()
    targets = {e.target for e in g.get_graph().edges if e.source == "save_doc"}
    # 저장 거부 재시도(menu_nav) + 정상 종료(__end__) 두 갈래.
    assert "menu_nav" in targets and "__end__" in targets


def test_recursion_limit_configured():
    g = build_trip_domestic_graph()
    assert g.config.get("recursion_limit") == RECURSION_LIMIT == 40


def test_gubun_label_uses_middle_dot():
    # P1 실측: 슬래시가 아니라 가운뎃점(·). 라벨이 정확해야 드롭다운 매칭이 된다.
    assert TRIP_GUBUN_LABEL == "출장(국내·자차)"


def test_graph_is_recompilable():
    assert build_trip_domestic_graph() is not None


# ── fixture 승격 검증 ─────────────────────────────────────────────────────────
def _trip_fixture() -> dict:
    return next(a for a in AGENT_FIXTURES if a["id"] == "trip-domestic")


def test_fixture_promoted_to_real_workflow():
    fx = _trip_fixture()
    assert fx["workflow_id"] == "trip-domestic"
    assert fx["flow_graph"] is not None
    assert fx["handoff_note"] and "상신" in fx["handoff_note"]


def test_fixture_step_keys_match_graph_nodes():
    fx = _trip_fixture()
    step_keys = {s["key"] for s in fx["steps"]}
    # 스텝 key 는 그래프 노드(emit_step 키)와 정확히 1:1 — 진행 하이라이트 정합.
    assert step_keys == _EXPECTED_NODES


def test_fixture_phases_cover_steps_in_order():
    fx = _trip_fixture()
    phases = [s["phase"] for s in fx["steps"]]
    # 연속 구간(접속→결의서 준비→건별 입력→저장).
    assert phases == [
        "접속", "접속", "접속", "접속",
        "결의서 준비", "결의서 준비", "결의서 준비",
        "건별 입력",
        "저장",
    ]
