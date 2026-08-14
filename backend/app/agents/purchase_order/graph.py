"""구매발주(purchase-order) — LangGraph StateGraph 조립 (Phase A: 읽기 + 계획서 HITL).

SCM-구매 첫 에이전트. 결의서(GLDDOC00300) 패밀리가 아니라 구매 3화면 파이프라인의 화면 ①
(프로젝트BOM구매요청 PUOPRQ00200)만 다룬다 — PROCESS.md D1(실행 중 HITL) 구현.

체인: login → user_type(SCM) → menu_nav(PUOPRQ00200) → pick_project(실행 전 선택 적용 —
      개입 없음, 실패는 하드) → read_bom → plan(HITL planner) → report → END.

⚠ Phase A 안전: 저장(F7)·결재 코드가 한 줄도 없다 — 런은 계획 확정 payload 를 결과로
  반환하고 끝난다. 쓰기(이동요청 저장·발주단위 저장·셀프 결재)는 실측 후 Phase B 에서 게이트
  개방한다.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.common.nodes import (
    make_login_node,
    make_menu_nav_node,
    make_user_type_node,
)
from app.agents.common.state import BaseAgentState
from nbkit.omnisol.menu_schemas import PURCHASE_ORDER_BOM, USER_TYPE_SCM

from .nodes import (
    make_pick_project_node,
    make_plan_node,
    make_read_bom_node,
    make_report_node,
)

RECURSION_LIMIT = 15


class PurchaseOrderState(BaseAgentState, total=False):
    """러너 주입 공통 키 상속 + 이 그래프 산출 키(LangGraph 미선언 키 silent drop)."""

    project: dict  # pick_project — {"code","name"} (read_bom 이 "wbs" 를 채워 갱신)
    planner_bom: dict  # read_bom — plannerBom(공유 계약 shape, plan 프레임에 실림)
    bom_summary: dict  # read_bom — 행수 요약(result.bomSummary)
    no_modules: bool  # 발주 대상 모듈 0 — read_bom 이 결과 메시지와 함께 조기 종료(→END)
    # plan 노드가 수락한 계획 payload(검증 통과분). ⚠ 키 이름이 노드명 'plan' 과 같으면
    # LangGraph 가 등록을 거부한다("already being used as a state key") — confirmed_plan 사용.
    confirmed_plan: dict


def build_purchase_order_graph():
    g = StateGraph(PurchaseOrderState)
    g.add_node("login", make_login_node())
    g.add_node("user_type", make_user_type_node(USER_TYPE_SCM))
    g.add_node("menu_nav", make_menu_nav_node(PURCHASE_ORDER_BOM))
    g.add_node("pick_project", make_pick_project_node())
    g.add_node("read_bom", make_read_bom_node())
    g.add_node("plan", make_plan_node())
    g.add_node("report", make_report_node())

    g.set_entry_point("login")
    for a, b in (
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "pick_project"),
        ("pick_project", "read_bom"),
        ("plan", "report"),
        ("report", END),
    ):
        g.add_edge(a, b)

    # 발주 대상 모듈 0건: read_bom 이 '발주할 모듈이 없습니다' 결과를 남기고 즉시 종료 —
    # 빈 계획서(HITL)를 띄워 사용자를 기다리게 하지 않는다(사용자 확정 2026-08-14).
    def _after_read_bom(state: PurchaseOrderState) -> str:
        return END if state.get("no_modules") else "plan"

    g.add_conditional_edges("read_bom", _after_read_bom, {"plan": "plan", END: END})
    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})
