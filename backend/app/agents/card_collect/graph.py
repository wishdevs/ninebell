"""법인카드 승인내역 정리(card-collect) — LangGraph StateGraph 조립.

진입 앞단(login→user_type(회계)→menu_nav(결의서입력)→set_gubun(카드)→add_row(F3)
→open_evdn→select_evdn(01))은 app.agents.common.nodes 를 그대로 재사용하고, 카드팝업 이후는
부가세구분 2패스: select_all_cards→set_period→query→collect_rows(그리드 1회 입력·과세 반영)
→save(1차 저장)→switch_evdn(불공 전환·재조회·매칭)→apply_pass2(불공 반영)→save_pass2.

state 계약(러너 주입): page/browser/events/userid/password/params. 종료는 save_pass2 가 result 로.
⚠ 저장(F7)은 save/save_pass2 노드가 사용자 HITL '저장' 선택 시에만 실행(그 외 절대 금지).
"""

from __future__ import annotations

from typing import Any, TypedDict

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

from .nodes import (
    make_apply_pass2_node,
    make_collect_rows_node,
    make_query_node,
    make_save_node,
    make_save_pass2_node,
    make_select_all_cards_node,
    make_set_period_node,
    make_switch_evdn_node,
)


class CardCollectState(TypedDict, total=False):
    page: Any
    browser: Any
    events: Any
    userid: str | None
    password: str | None
    params: dict
    owner: str | None  # HITL 소유자(세션 사용자 id) — 채널 오픈 시 바인딩(러너 주입)
    run_id: str | None  # 세션/런 id — HITL 런바인딩(러너 주입)
    period: list[str]
    rows_list: list[dict]
    filled: int
    # 부가세구분 2패스 — 1차 그리드 입력 중 불공 대기분(입력값+복합키)과 2차 산출물.
    pending_nontax: list[dict]
    save_cancelled: bool
    rows2_list: list[dict]
    pass2_work: list[dict]
    pass2_unmatched: int
    pass2_filled: int
    result: str | dict
    error: str


def build_card_collect_graph():
    """법인카드 승인내역 정리 체인을 컴파일해 반환(stateless·재사용 가능)."""
    g = StateGraph(CardCollectState)
    # 진입 앞단(재사용)
    g.add_node("login", make_login_node())
    g.add_node("user_type", make_user_type_node("회계"))
    g.add_node("menu_nav", make_menu_nav_node())
    g.add_node("set_gubun", make_set_gubun_node("카드"))
    g.add_node("add_row", make_add_row_node())
    g.add_node("open_evdn", make_open_evdn_node())
    g.add_node("select_evdn", make_select_evdn_node("01"))  # 법인카드
    # 카드팝업 이후(신규)
    g.add_node("select_all_cards", make_select_all_cards_node())
    g.add_node("set_period", make_set_period_node())
    g.add_node("query", make_query_node())
    g.add_node("collect_rows", make_collect_rows_node())
    g.add_node("save", make_save_node())
    # 2차(불공) — 증빙유형 전환·재조회·매칭 → 반영 → 저장.
    g.add_node("switch_evdn", make_switch_evdn_node())
    g.add_node("apply_pass2", make_apply_pass2_node())
    g.add_node("save_pass2", make_save_pass2_node())

    g.set_entry_point("login")
    for a, b in [
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "set_gubun"),
        ("set_gubun", "add_row"),
        ("add_row", "open_evdn"),
        ("open_evdn", "select_evdn"),
        ("select_evdn", "select_all_cards"),
        ("select_all_cards", "set_period"),
        ("set_period", "query"),
        ("query", "collect_rows"),
        ("collect_rows", "save"),
        ("save", "switch_evdn"),
        ("switch_evdn", "apply_pass2"),
        ("apply_pass2", "save_pass2"),
    ]:
        g.add_edge(a, b)
    g.add_edge("save_pass2", END)
    return g.compile()
