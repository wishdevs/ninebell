"""전자결재 상신 취소(eap-approval-cancel) — LangGraph StateGraph 조립.

결의서입력(문서 생성)·전표조회승인(조회+결재) 어느 계열도 아닌 **전자결재(EAP) 취소** 아키타입.
결의서 화면(dews)이 아니라 GNB '전자결재' 안의 React 앱(iframe #content_UB)을 다루므로
사용자유형 전환도, 메뉴 딥링크(navigate_schema)도 쓰지 않는다.

체인: login → enter_eap → list_docs(HITL multiselect) → cancel_docs → END.

⚠ 안전: 상신·저장(F7)·보관은 클릭하지 않는다(steps.ALLOWED_BUTTONS 가 마지막 방어선).
  세 단계(결재취소·상신취소·삭제)는 비가역이라 사용자가 체크한 문서에만 실행하며,
  hidden 워크플로우라 실행 경로는 관리자 + 프론트 디버그 모드 버튼뿐이다.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.common.nodes import make_login_node
from app.agents.common.state import BaseAgentState

from .nodes import make_cancel_docs_node, make_enter_eap_node, make_list_docs_node

RECURSION_LIMIT = 10


class EapCancelState(BaseAgentState, total=False):
    """러너 주입 공통 키 상속 + 이 그래프 산출 키(LangGraph 미선언 키 silent drop)."""

    picked: list[str]  # list_docs — 사용자가 체크한 문서 제목
    cancelled: list[str]  # cancel_docs — 3단계까지 끝나 잔존 0 확인된 문서 제목


def build_eap_cancel_graph():
    g = StateGraph(EapCancelState)
    g.add_node("login", make_login_node())
    g.add_node("enter_eap", make_enter_eap_node())
    g.add_node("list_docs", make_list_docs_node())
    g.add_node("cancel_docs", make_cancel_docs_node())

    g.set_entry_point("login")
    for a, b in (
        ("login", "enter_eap"),
        ("enter_eap", "list_docs"),
        ("list_docs", "cancel_docs"),
        ("cancel_docs", END),
    ):
        g.add_edge(a, b)
    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})
