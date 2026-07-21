"""전표조회승인(voucher-receivable) — LangGraph StateGraph 조립.

결의서입력(문서 생성) 계열과 다른 **조회+결재** 아키타입이다: 조회 조건을 세팅해 미결·전자결재저장
상태의 매출전표를 조회하고, 대상을 한 건씩 결제창까지 열어 **가상 상신 로그만 남기고 닫는다**
(실제 상신·저장·삭제 없음). HITL 없음(무개입 완주).

체인: validate_params(브라우저 앞·배치 게이트) → login → user_type(회계)
      → menu_nav(전표조회승인) → set_query → run_query → loop_approvals → END.

⚠ 안전: loop_approvals 는 결제창에서 상신·보관을 절대 클릭하지 않는다(nodes/approvals.py 참조).
  기본 **전체 진행**(max_rows=None → 조회된 전 건 순회, 사용자 결정 2026-07-21). max_rows 를
  명시하면 그 수만큼만.

⚠ validate_params 를 앞단에 둔 것은 프로브/과제 개요의 조립(login→…→loop)에 더한 최소 추가다 —
  형제 실동작 워크플로우(trip/gyeongjo/hakjagum)와 동일 관례이며, params 검증을 브라우저/EAP
  접촉 전에 두기 위함이다.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.common.nodes import (
    make_login_node,
    make_menu_nav_node,
    make_user_type_node,
)
from app.agents.common.state import BaseAgentState
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE

from . import steps  # 전표유형 상수(DOCU_TYPES_RECEIVABLE/PAYABLE)
from .nodes import (
    make_loop_approvals_node,
    make_run_query_node,
    make_set_query_node,
    make_validate_params_node,
)

# 선형 체인(재시도 루프 없음) — 노드 7개면 recursion_limit 기본으로 충분하나 명시해 회귀 방지.
RECURSION_LIMIT = 20


class VoucherReceivableState(BaseAgentState, total=False):
    """러너 주입 공통 키(page/…/result/error)는 BaseAgentState 상속.

    ⚠ 노드가 반환하는 키는 전부 여기 선언돼야 다음 노드로 전달된다(LangGraph 미선언 키 silent drop).
    """

    max_rows: int | None  # validate_params 산출 — 처리 최대 행 수(None=전체)
    master_rowcount: int  # run_query 산출 — 조회 결과 마스터 그리드 행 수
    processed: int  # loop_approvals — 가상 상신 처리 건수
    processed_docu_nos: list[str]  # 가상 상신한 전표번호(DOCU_NO) 목록


def build_voucher_graph(
    docu_types: tuple[str, ...],
    *,
    state_cls: type = VoucherReceivableState,
    validate_node=None,
    pre_loop_node=None,
    on_popup=None,
):
    """전표조회승인 조회+결재 체인을 컴파일해 반환(stateless·재사용).

    전표유형(docu_types)만 에이전트별로 다르고 나머지(조회 8필드·결과그리드·checkRow·결제창·
    D7·로딩대기·진행)는 전부 공유한다 — 외상매출금/외상매입금이 이 빌더를 값만 바꿔 쓴다.

    카드(미지급금 법인카드) 확장을 위한 optional 훅(전부 기본 None → 매출/매입 무영향):
      state_cls      그래프 State TypedDict(신규 키 선언용). 카드는 payment_map 등을 더한
                     서브클래스를 넘긴다(미선언 키는 LangGraph silent drop).
      validate_node  진입 검증 노드 override(카드는 회계일 override 를 파싱). None=공유.
      pre_loop_node  run_query 와 loop_approvals **사이**에 삽입할 노드(카드=collect_payments,
                     결의서조회승인 다중탭에서 ABDOCU_NO→GWDOCU_NO 맵 수집). None=미삽입.
      on_popup       loop_approvals 결제창 훅(카드=참조문서 선택). None=미호출.
    """
    g = StateGraph(state_cls)
    # 진입 앞단: validate_params(브라우저 앞) → 공유 프리미티브(login/user_type/menu_nav).
    g.add_node("validate_params", validate_node or make_validate_params_node())
    g.add_node("login", make_login_node())
    g.add_node("user_type", make_user_type_node("회계"))
    g.add_node("menu_nav", make_menu_nav_node(VOUCHER_RECEIVABLE))
    # 신규(조회 조건·조회·결재 순회) — set_query 만 전표유형 파라미터를 받는다.
    g.add_node("set_query", make_set_query_node(docu_types))
    g.add_node("run_query", make_run_query_node())
    g.add_node("loop_approvals", make_loop_approvals_node(on_popup=on_popup))

    edges = [
        ("validate_params", "login"),
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "set_query"),
        ("set_query", "run_query"),
    ]
    if pre_loop_node is not None:
        # run_query → collect_payments → loop_approvals(카드) — 매출/매입은 직결(아래 else).
        g.add_node("collect_payments", pre_loop_node)
        edges += [("run_query", "collect_payments"), ("collect_payments", "loop_approvals")]
    else:
        edges += [("run_query", "loop_approvals")]
    edges += [("loop_approvals", END)]

    g.set_entry_point("validate_params")
    for a, b in edges:
        g.add_edge(a, b)

    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})


def build_voucher_receivable_graph():
    """외상매출금(voucher-receivable) — 전표유형 국내매출+해외매출."""
    return build_voucher_graph(steps.DOCU_TYPES_RECEIVABLE)


def build_voucher_payable_graph():
    """외상매입금(voucher-payable) — 전표유형 내수구매. 나머지 전부 공유."""
    return build_voucher_graph(steps.DOCU_TYPES_PAYABLE)
