"""경조금신청서 결의서입력(gyeongjo-grant) — LangGraph StateGraph 조립.

국내/해외출장과 기본틀 동일 — HITL 없음(모든 입력은 실행 전 폼 → params). 진입 앞단(login→
user_type→menu_nav→set_gubun→add_row)은 app.agents.common.nodes 를 재사용하고, 회계일·단건 채움·
저장만 신규다. 증빙(open/select)은 fill_rows 내부에서 처리한다.

경조금 델타: 결의구분 라벨(경조금신청서, value 55)·단건(1행)·거래처 본인·예산단위 복리후생비-경조·
공급가액 백엔드 계산(근속<1년 50%)·적요 '경조금-{본인}'. 회계일자 = 증빙일자(단건이라 그대로).

체인: validate_params(브라우저 앞) → login → user_type(회계) → menu_nav → set_gubun(경조금신청서)
→ add_row(F3) → set_acct_date → fill_rows → save_doc → [retry_save? → menu_nav | END].

⚠ 저장(F7)은 save_doc 이 filled>0 일 때만 1회 실행. ERP 거부 시 MAX_SAVE_RETRIES 까지 재입력.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.common.nodes import (
    make_add_row_node,
    make_login_node,
    make_menu_nav_node,
    make_set_gubun_node,
    make_user_type_node,
)
from app.agents.common.state import BaseAgentState

from .nodes import (
    make_fill_rows_node,
    make_save_doc_node,
    make_set_acct_date_node,
    make_validate_params_node,
)

# 결의구분 라벨(2026-07-13 실측 gyeongjo_probe.py): "경조금신청서" = value 55(국내출장 53 대비).
GYEONGJO_GUBUN_LABEL = "경조금신청서"

# 재시도 루프 상한 — 체인 ~9노드 × (초기+2재시도) ≈ 27 < 40.
RECURSION_LIMIT = 40


class GyeongjoGrantState(BaseAgentState, total=False):
    """러너 주입 공통 키(page/…/result/error)는 BaseAgentState 상속.

    ⚠ 노드가 반환하는 키는 전부 여기 선언돼야 다음 노드로 전달된다(LangGraph 미선언 키 silent drop).
    """

    plan_rows: list[dict]  # validate_params 산출 — 정규화된 단건 행(invoiceDate/amount/project/baseAmount/under1Year)
    acct_date_compact: str  # 마스터 회계일 'YYYYMMDD'(= 증빙일)
    department: str  # 예산단위 조합용 부서(BG_NM) — params 주입
    cost_type: str  # 비용구분(판관비/제조원가) — 예산계정 (판)/(제) 접두 결정
    filled: int  # 반영 완료 행 수(단건이라 0 또는 1)
    fill_failures: list[dict]  # [{row, field, reason}] — 실패 진단
    # 저장 거부 → 재입력 재시도(방식 1: menu_nav 재진입으로 문서 새로 만들기).
    retry_save: bool
    save_retries: int
    save_error_msg: str


def build_gyeongjo_grant_graph():
    """경조금신청서 체인을 컴파일해 반환(stateless·재사용 가능)."""
    g = StateGraph(GyeongjoGrantState)
    # 진입 앞단(공유 재사용) — validate_params 만 브라우저 앞.
    g.add_node("validate_params", make_validate_params_node())
    g.add_node("login", make_login_node())
    g.add_node("user_type", make_user_type_node("회계"))
    g.add_node("menu_nav", make_menu_nav_node())
    g.add_node("set_gubun", make_set_gubun_node(GYEONGJO_GUBUN_LABEL))
    g.add_node("add_row", make_add_row_node())
    # 신규(본문 채움·저장)
    g.add_node("set_acct_date", make_set_acct_date_node())
    g.add_node("fill_rows", make_fill_rows_node())
    g.add_node("save_doc", make_save_doc_node())

    g.set_entry_point("validate_params")
    for a, b in [
        ("validate_params", "login"),
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "set_gubun"),
        ("set_gubun", "add_row"),
        ("add_row", "set_acct_date"),
        ("set_acct_date", "fill_rows"),
        ("fill_rows", "save_doc"),
    ]:
        g.add_edge(a, b)

    # 저장 거부 재시도: retry_save 가 켜지면 menu_nav 로 되돌려 문서를 새로 만든다. 아니면 종료.
    def _after_save(state: GyeongjoGrantState) -> str:
        return "menu_nav" if state.get("retry_save") else END

    g.add_conditional_edges("save_doc", _after_save, {"menu_nav": "menu_nav", END: END})
    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})
