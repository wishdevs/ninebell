"""세금계산서 결의서입력(tax-invoice) — LangGraph StateGraph 조립.

진입 앞단(login→회계 유저타입→menu_nav→set_gubun(세금계산서 51)→add_row)은
`app.agents.common.nodes` + 결의구분 확인 래퍼(hakjagum gubun 노드)를 재사용하고,
증빙유형(다이얼로그 처리)·발행 후 계산서 HITL·본문 채움·비용분할·저장만 신규다.

체인(선형 — 해당 없는 노드는 스스로 스킵하고 스텝만 닫는다):
validate_params(브라우저 앞) → login → user_type(회계) → menu_nav → set_gubun(세금계산서)
→ add_row(F3) → select_evdn → pick_invoices(발행 후 개입) → apply_invoices(발행 후 적용·행별
채움) → fill_rows(발행 전 폼 채움) → split_costs(분할) → save_doc → END.

⚠ 저장(F7)은 save_doc 이 filled>0 일 때만 1회 실행. 상신 절대 금지(사용자가 ERP 에서 직접).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.common.nodes import (
    make_add_row_node,
    make_login_node,
    make_menu_nav_node,
    make_user_type_node,
)
from app.agents.common.state import BaseAgentState
from app.agents.hakjagum_grant.nodes.gubun import make_confirmed_set_gubun_node

from .nodes import (
    make_apply_invoices_node,
    make_fill_rows_node,
    make_pick_invoices_node,
    make_save_doc_node,
    make_select_evdn_node,
    make_split_costs_node,
    make_validate_params_node,
)

# 결의구분 라벨 — 실측(2026-08-19 읽기 프로브 D3): 라벨 "세금계산서" = value "51". 검증:✅.
TAX_INVOICE_GUBUN_LABEL = "세금계산서"
TAX_INVOICE_FG_CODE = "51"  # 마스터 ABDOCU_FG_CD — e2e 삭제 가드레일이 이 코드로 식별.


class TaxInvoiceState(BaseAgentState, total=False):
    """러너 주입 공통 키(page/…/result/error)는 BaseAgentState 상속.

    ⚠ 노드가 반환하는 키는 전부 여기 선언돼야 다음 노드로 전달된다(LangGraph 미선언 키 silent drop).
    """

    plan: dict  # validate_params 산출 — 정규화된 실행 계획(증빙코드·금액·분할 계획 등)
    invoice_picked: list[int]  # 발행 후 HITL 에서 사용자가 고른 계산서 행 인덱스
    invoice_selection: list[dict]  # 행별 입력까지 담긴 선택(no·index·예산단위·프로젝트·적요)
    split_plan: list[dict]  # 개입에서 받은 분할 계획(발행 후) — split_costs 가 소비
    aborted: bool  # HITL 빈 선택 등 우아한 종료(오류 아님 — 이후 노드 스킵)
    filled: int  # 본문 반영 완료(0|1) — save_doc 게이트
    fill_warnings: list[str]  # 반영을 **확인하지 못한** 필드명(값이 틀린 게 아니라 확인 불가)
    split_done: bool  # 분할처리 팝업 '적용' 확정 완료


def build_tax_invoice_graph():
    """세금계산서 체인을 컴파일해 반환(stateless·재사용 가능)."""
    g = StateGraph(TaxInvoiceState)
    # 진입 앞단(공유 재사용) — validate_params 만 브라우저 앞.
    g.add_node("validate_params", make_validate_params_node())
    g.add_node("login", make_login_node())
    g.add_node("user_type", make_user_type_node("회계"))
    g.add_node("menu_nav", make_menu_nav_node())
    # 결의구분은 세팅 후 선택 텍스트 재확인까지(다른 문서 종류 채움 사고 방지 — hakjagum 래퍼 재사용).
    g.add_node("set_gubun", make_confirmed_set_gubun_node(TAX_INVOICE_GUBUN_LABEL))
    g.add_node("add_row", make_add_row_node())
    # 신규(증빙·계산서 HITL·본문·분할·저장)
    g.add_node("select_evdn", make_select_evdn_node())
    g.add_node("pick_invoices", make_pick_invoices_node())
    g.add_node("apply_invoices", make_apply_invoices_node())
    g.add_node("fill_rows", make_fill_rows_node())
    g.add_node("split_costs", make_split_costs_node())
    g.add_node("save_doc", make_save_doc_node())

    g.set_entry_point("validate_params")
    for a, b in [
        ("validate_params", "login"),
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "set_gubun"),
        ("set_gubun", "add_row"),
        ("add_row", "select_evdn"),
        ("select_evdn", "pick_invoices"),
        ("pick_invoices", "apply_invoices"),
        ("apply_invoices", "fill_rows"),
        ("fill_rows", "split_costs"),
        ("split_costs", "save_doc"),
    ]:
        g.add_edge(a, b)
    g.add_edge("save_doc", END)
    return g.compile()
