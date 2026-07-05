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


class CardCollectState(BaseAgentState, total=False):
    """러너 주입 공통 키는 BaseAgentState 상속(page/browser/events/…/result/error)."""

    period: list[str]
    rows_list: list[dict]
    filled: int
    no_rows: bool  # 조회 0건 — collect_rows 가 결과 메시지와 함께 그래프를 조기 종료(→END)
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
    # 저장 실패 → 그리드 재선택 재시도(방식 1: 문서 리셋 후 재실행, 상한 MAX_SAVE_RETRIES).
    retry_save: bool  # save_final 이 재시도 신호를 켠다(라우터가 menu_nav 로 되돌림)
    save_retries: int  # 누적 재시도 횟수(상한 초과 시 실패 종료)
    save_error_msg: str  # 직전 저장 실패 사유(재진입한 그리드에 표시)
    save_error_issues: list[dict]  # 파싱된 조치 안내 [{aprvlNo, requiredAccount, rowNo, merchant, raw}]
    retry_prefill: dict  # {row_key: {budgetUnit, project, note, skip}} — 재시도 시 이전 선택 보존


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
        ("apply_doc", "switch_evdn"),
        ("switch_evdn", "apply_pass2"),
        ("apply_pass2", "save_final"),
    ]:
        g.add_edge(a, b)

    # 조회 0건: collect_rows 가 '처리할 내역이 없습니다' 결과를 남기고 즉시 종료 —
    # 뒤 단계(문서 반영·저장)를 돌리지 않는다(사용자 확정 2026-07-05).
    def _after_collect(state: CardCollectState) -> str:
        return END if state.get("no_rows") else "apply_doc"

    g.add_conditional_edges("collect_rows", _after_collect, {"apply_doc": "apply_doc", END: END})

    # 저장 실패 재시도(방식 1): retry_save 가 켜지면 menu_nav 로 되돌려 문서를 새로 만들고
    # (딥링크 재로드로 저장 안 된 초안 폐기) 그리드부터 재입력한다. 아니면 종료.
    def _after_save(state: CardCollectState) -> str:
        return "menu_nav" if state.get("retry_save") else END

    g.add_conditional_edges("save_final", _after_save, {"menu_nav": "menu_nav", END: END})
    # 재시도 루프(최대 2회)는 체인(~15노드)을 3회까지 재실행 → 기본 recursion_limit(25) 초과.
    # 3패스(~45) + 여유로 60 으로 올린다.
    return g.compile().with_config({"recursion_limit": 60})
