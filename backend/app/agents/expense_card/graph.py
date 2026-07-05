"""법인카드 대화형 지결 그래프 — LangGraph StateGraph 조립.

체인: login → user_type(회계) → menu_nav(EXPENSE_CARD) → set_gubun(카드) → add_row(F3)
→ open_evdn → select_evdn(01 법인카드) → chat_form. 프로젝트는 chat_form 안에서 fill_search
로 처리(별도 project HITL 노드 없음).

state 계약(러너가 주입): page/browser/events/userid/password/params. 실패는 노드가
{"error": ...} 로 남기고 이후 노드가 건너뛴다. 종료는 chat_form 이 result 로.

⚠ 저장(F7)·상신 절대 금지 — 모달 '적용'까지만.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.common.nodes import (
    make_add_row_node,
    make_login_node,
    make_menu_nav_node,
    make_open_evdn_node,
    make_select_evdn_node,
    make_set_gubun_node,
    make_user_type_node,
)
from app.agents.common.state import BaseAgentState

from .chat_form import make_chat_form_node


class ExpenseCardState(BaseAgentState, total=False):
    """대화형 법인카드 지결 그래프 state — 러너 계약은 BaseAgentState 상속, 추가 키 없음.

    result 는 대화형이면 {"summary","selections"} 구조(템플릿 저장용), AUTO 재생은 요약
    문자열 — 러너가 그대로 result 프레임으로 흘리고 run.result 로 영속한다.
    ⚠ 노드가 새 키를 반환하면 여기 선언해야 다음 노드로 전달된다(미선언 키는 LangGraph 가
      조용히 누락).
    """


def build_expense_card_chat_graph():
    """법인카드 대화형 지결 체인을 컴파일해 반환(stateless·재사용 가능)."""
    g = StateGraph(ExpenseCardState)
    g.add_node("login", make_login_node())
    g.add_node("user_type", make_user_type_node("회계"))
    g.add_node("menu_nav", make_menu_nav_node())
    g.add_node("set_gubun", make_set_gubun_node("카드"))
    g.add_node("add_row", make_add_row_node())
    g.add_node("open_evdn", make_open_evdn_node())
    g.add_node("select_evdn", make_select_evdn_node("01"))  # 증빙유형 자동선택(법인카드)
    g.add_node("chat_form", make_chat_form_node())
    g.set_entry_point("login")
    g.add_edge("login", "user_type")
    g.add_edge("user_type", "menu_nav")
    g.add_edge("menu_nav", "set_gubun")
    g.add_edge("set_gubun", "add_row")
    g.add_edge("add_row", "open_evdn")
    g.add_edge("open_evdn", "select_evdn")
    g.add_edge("select_evdn", "chat_form")
    g.add_edge("chat_form", END)
    return g.compile()
