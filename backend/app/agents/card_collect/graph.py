"""법인카드 승인내역 정리(card-collect) — LangGraph StateGraph 조립.

진입 앞단(login→user_type(회계)→menu_nav(결의서입력)→set_gubun(카드)→add_row(F3)
→set_acct_date(회계일=기간월 말일)→open_evdn→select_evdn(01))은 app.agents.common.nodes 를 그대로 재사용하고, 카드팝업 이후는
부가세구분 2패스: select_all_cards→set_period→query→collect_rows(그리드 1회 입력·과세 반영)
→apply_doc(과세 적용)→switch_evdn(F3·불공 전환·재조회·매칭)→apply_pass2(불공 반영·적용)
→save_final(최종 저장 F7 — 마지막 1회, 사용자 업무 규칙).

state 계약(러너 주입): page/browser/events/userid/password/params. 종료는 save_final 이 result 로.
⚠ 저장(F7)은 save_final 노드가 사용자 HITL '저장' 선택 시에만 1회 실행(그 외 절대 금지).
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
    make_apply_doc_node,
    make_apply_pass2_node,
    make_collect_rows_node,
    make_query_node,
    make_save_final_node,
    make_select_all_cards_node,
    make_set_acct_date_node,
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
    # ⚠ 노드가 반환하는 키는 여기 선언돼야 다음 노드로 전달된다(미선언 키는 LangGraph 가
    #   조용히 누락 — 실전 런 '적용할 행이 없습니다' 원인).
    pending_nontax: list[dict]
    pass1_applied_idx: list[int]  # 1차 반영 성공 행 인덱스(카드팝업 '적용' 체크 대상)
    pass1_failed: int  # 1차 행 채움 실패 수 — 전량 실패 시 save_final 이 실패로 보고
    pass1_doc_applied: bool  # 1차 적용('적용' 클릭·문서 반영) 실행됨 → 2차는 F3(새 행)부터
    rows2_list: list[dict]
    pass2_work: list[dict]
    pass2_unmatched: int
    pass2_unmatched_desc: str
    pass2_filled: int
    pass2_applied_idx: list[int]
    pass2_failed: int
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
    # 회계일 = 수집 기간 월의 말일(사용자 규칙 2026-07-04) — F3 로 생긴 마스터 행에,
    # 카드 팝업이 뜨기 전(메인 화면) 시점에 설정한다.
    g.add_node("set_acct_date", make_set_acct_date_node())
    g.add_node("open_evdn", make_open_evdn_node())
    g.add_node("select_evdn", make_select_evdn_node("01"))  # 법인카드
    # 카드팝업 이후(신규)
    g.add_node("select_all_cards", make_select_all_cards_node())
    g.add_node("set_period", make_set_period_node())
    g.add_node("query", make_query_node())
    g.add_node("collect_rows", make_collect_rows_node())
    # 저장(F7)은 마지막 1회 — 1차는 적용(문서 반영)만 하고 F3 새 행으로 2차 진행.
    g.add_node("apply_doc", make_apply_doc_node())
    g.add_node("switch_evdn", make_switch_evdn_node())
    g.add_node("apply_pass2", make_apply_pass2_node())
    g.add_node("save_final", make_save_final_node())

    g.set_entry_point("login")
    for a, b in [
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "set_gubun"),
        ("set_gubun", "add_row"),
        ("add_row", "set_acct_date"),
        ("set_acct_date", "open_evdn"),
        ("open_evdn", "select_evdn"),
        ("select_evdn", "select_all_cards"),
        ("select_all_cards", "set_period"),
        ("set_period", "query"),
        ("query", "collect_rows"),
        ("collect_rows", "apply_doc"),
        ("apply_doc", "switch_evdn"),
        ("switch_evdn", "apply_pass2"),
        ("apply_pass2", "save_final"),
    ]:
        g.add_edge(a, b)
    g.add_edge("save_final", END)
    return g.compile()
