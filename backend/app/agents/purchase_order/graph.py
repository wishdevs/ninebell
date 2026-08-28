"""구매발주(purchase-order) — LangGraph StateGraph 조립 (Phase A 읽기+계획서 HITL → Phase B 쓰기).

SCM-구매 첫 에이전트. 구매 3화면 파이프라인의 화면 ①(프로젝트BOM구매요청 PUOPRQ00200) 쓰기와
화면 ②(구매요청처리 PUOPRQ00300) 셀프결재까지 — PROCESS.md D1·D4·D5·D7 구현(2026-08-28 개방,
사용자 지시: ETRI-001 헤디드 실행). 화면 ③(구매발주일괄입력)은 아직 없다.

체인: login → user_type(SCM) → menu_nav(PUOPRQ00200) → pick_project → read_bom
      → plan(HITL planner) → confirm_write(HITL confirm, 중단이면 END)
      → save_move(이동요청 저장 1회) → save_units(발주단위별 구매요청 저장)
      → self_approve(화면 ② 진입 → HITL confirm → EAP 상신) → report → END.

게이트: 저장은 계획 확정 + confirm_write 승인 뒤. 상신은 빌더 allow_submit(True) ∧ ¬params.debug
∧ 상신 직전 confirm 승인. ⛔ 보관 미클릭.
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
    make_confirm_write_node,
    make_pick_project_node,
    make_plan_node,
    make_read_bom_node,
    make_report_node,
    make_save_move_node,
    make_save_units_node,
    make_self_approve_node,
)

RECURSION_LIMIT = 20


class PurchaseOrderState(BaseAgentState, total=False):
    """러너 주입 공통 키 상속 + 이 그래프 산출 키(LangGraph 미선언 키 silent drop)."""

    project: dict  # pick_project — {"code","name"} (read_bom 이 "wbs" 를 채워 갱신)
    planner_bom: dict  # read_bom — plannerBom(공유 계약 shape, plan 프레임에 실림)
    bom_summary: dict  # read_bom — 행수 요약(result.bomSummary)
    no_modules: bool  # 발주 대상 모듈 0 — read_bom 이 결과 메시지와 함께 조기 종료(→END)
    # plan 노드가 수락한 계획 payload(검증 통과분). ⚠ 키 이름이 노드명 'plan' 과 같으면
    # LangGraph 가 등록을 거부한다("already being used as a state key") — confirmed_plan 사용.
    confirmed_plan: dict
    write_aborted: bool  # confirm_write — 사용자가 저장을 진행하지 않음(→END, 실패 아님)
    move_request_no: str | None  # save_move — 이동요청번호(IRQ…), 대상 0건이면 None
    purchase_request_nos: list  # save_units — [{seq, number(PRQ…), modules, dueDate, purchaseReason}]
    submitted: list  # self_approve — [{number, submitted, status?, gwdocuNo?}]
    debug_mode: bool  # 러너/검증이 넣는 디버그 플래그(상신 게이트 런타임 차단)


def build_purchase_order_graph(*, allow_submit: bool = True):
    g = StateGraph(PurchaseOrderState)
    g.add_node("login", make_login_node())
    g.add_node("user_type", make_user_type_node(USER_TYPE_SCM))
    g.add_node("menu_nav", make_menu_nav_node(PURCHASE_ORDER_BOM))
    g.add_node("pick_project", make_pick_project_node())
    g.add_node("read_bom", make_read_bom_node())
    g.add_node("plan", make_plan_node())
    g.add_node("confirm_write", make_confirm_write_node())
    g.add_node("save_move", make_save_move_node())
    g.add_node("save_units", make_save_units_node())
    g.add_node("self_approve", make_self_approve_node(allow_submit=allow_submit))
    g.add_node("report", make_report_node())

    g.set_entry_point("login")
    for a, b in (
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "pick_project"),
        ("pick_project", "read_bom"),
        ("plan", "confirm_write"),
        ("save_move", "save_units"),
        ("save_units", "self_approve"),
        ("self_approve", "report"),
        ("report", END),
    ):
        g.add_edge(a, b)

    # 발주 대상 모듈 0건: read_bom 이 '발주할 모듈이 없습니다' 결과를 남기고 즉시 종료 —
    # 빈 계획서(HITL)를 띄워 사용자를 기다리게 하지 않는다(사용자 확정 2026-08-14).
    def _after_read_bom(state: PurchaseOrderState) -> str:
        # 재실행 경로: params.purchase_order.submit_prqs 가 있으면 계획/저장을 건너뛰고 이미 저장된
        # 구매요청번호만 셀프결재 상신한다(2026-08-28 — 저장은 됐는데 상신 전 중단된 런 복구용).
        po = (state.get("params") or {}).get("purchase_order") or {}
        if po.get("submit_prqs"):
            return "self_approve"
        return END if state.get("no_modules") else "plan"

    g.add_conditional_edges(
        "read_bom", _after_read_bom, {"plan": "plan", "self_approve": "self_approve", END: END}
    )

    # 사용자가 저장을 진행하지 않으면 계획 확정 결과만 남기고 끝낸다(저장 0건).
    def _after_confirm(state: PurchaseOrderState) -> str:
        return END if state.get("write_aborted") else "save_move"

    g.add_conditional_edges("confirm_write", _after_confirm, {"save_move": "save_move", END: END})
    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})
