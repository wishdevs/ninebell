"""전표조회승인(voucher-by-type) — LangGraph StateGraph 조립.

결의서입력(문서 생성) 계열과 다른 **조회+결재** 아키타입이다: 조회 조건을 세팅해 미결·전자결재저장
상태의 매출전표를 조회하고, 대상을 결제창까지 열어 **상신(allow_submit 게이트)까지 실행한다**
(정책 전환 2026-08-07 — 상신은 EAP 취소 e2e 로 가역. 저장·삭제·보관은 여전히 없음).
HITL 없음(무개입 완주).

체인: validate_params(브라우저 앞·배치 게이트) → login → user_type(회계)
      → menu_nav(전표조회승인) → set_query → run_query → loop_approvals → END.

⚠ 안전: 상신은 allow_submit 게이트(기본 False, 3종 빌더가 개방) 뒤에서만 실클릭하고, 보관은
  게이트와 무관하게 절대 클릭하지 않는다(nodes/approvals.py 참조). 기본 **전체 진행**
  (max_rows=None → 조회된 전 건 순회, 사용자 결정 2026-07-21). max_rows 명시 시 그 수만큼만.

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

from . import steps  # 전표유형 상수(DOCU_TYPE_CHOICES 등)
from .batching import DETAIL_BATCH_LIMIT
from .nodes import (
    make_batch_approvals_node,
    make_count_details_node,
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
    period_from: str | None  # validate_params 산출 — 회계일 조회 시작일 YYYYMMDD(None=당월)
    period_to: str | None  # validate_params 산출 — 회계일 조회 종료일 YYYYMMDD(None=당월)
    docu_types: list[str] | None  # validate_params 산출 — 전표유형 선택(None=빌드 기본 전체)
    menu_filters: list[str] | None  # validate_params 산출 — 메뉴(MENU_NM) 필터(None=미필터)
    debug_mode: bool  # validate_params 산출 — True 면 상신 게이트 런타임 강제 닫힘(가상 상신)
    master_rowcount: int  # run_query 산출 — 조회 결과 마스터 그리드 행 수
    processed: int  # loop_approvals — 상신(게이트 개방) 또는 가상 상신 처리 건수
    processed_docu_nos: list[str]  # 상신/가상 상신한 전표번호(DOCU_NO) 목록
    # ── 배치 결재 모드(batch_limit 지정 시에만 채워진다 — 매입/카드는 미사용) ──────
    detail_counts: dict  # count_details — 전표번호 → 하위(계정정보) 건수(-1=미상)
    approval_plan: list  # count_details — 결재 순서대로의 그룹 목록(단독 먼저 → 묶음)


def build_voucher_graph(
    docu_types: tuple[str, ...],
    *,
    state_cls: type = VoucherReceivableState,
    validate_node=None,
    pre_loop_node=None,
    on_popup=None,
    batch_limit=None,
    allow_submit: bool = False,
):
    """전표조회승인 조회+결재 체인을 컴파일해 반환(stateless·재사용).

    전표유형(docu_types)만 에이전트별로 다르고 나머지(조회 8필드·결과그리드·checkRow·결제창·
    D7·로딩대기·진행)는 전부 공유한다 — 유형별 전표조회 승인(voucher-by-type)·카드가 이 빌더를
    값만 바꿔 쓴다. docu_types 는 **빌드 기본값**이고, state.docu_types(실행 전 폼 선택)가
    있으면 set_query 가 그것을 우선한다(2026-08-20 매출/매입 병합).

    카드(미지급금 법인카드) 확장을 위한 optional 훅(전부 기본 None → 매출/매입 무영향):
      state_cls      그래프 State TypedDict(신규 키 선언용). 카드는 payment_map 등을 더한
                     서브클래스를 넘긴다(미선언 키는 LangGraph silent drop).
      validate_node  진입 검증 노드 override(카드는 회계일 override 를 파싱). None=공유.
      pre_loop_node  run_query 와 loop_approvals **사이**에 삽입할 노드(카드=collect_payments,
                     결의서조회승인 다중탭에서 ABDOCU_NO→GWDOCU_NO 맵 수집). None=미삽입.
      on_popup       loop_approvals 결제창 훅(카드=참조문서 선택). None=미호출.
      batch_limit    **배치 결재 모드**(매출 2026-07-27 → 매입 확대 2026-08-07 사용자 확정).
                     지정하면 run_query 뒤에 count_details 노드를 넣어 전표별 하위(계정정보)
                     건수를 파악하고, 하위 단독 batch_limit 이상은 단독으로 먼저, 나머지는
                     합계가 batch_limit 미만이 되도록 묶어 **한 번에** 결재창을 연다(실측:
                     다중 체크 후 결재 1회 → 자식창 1개에 대상 전부 표시).
                     None(기본)=건별 순회(카드 기존 동작 그대로 — 결제창마다 행별 참조문서).
      allow_submit   결제창 '상신' 실클릭 게이트(기본 False=가상 상신 로그만). voucher 3종
                     빌더가 True 로 연다(정책 전환 2026-08-07 — EAP 취소 e2e 로 가역).
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
    # 배치 모드는 결재 노드 자체가 다르다(그룹 단위 체크·1회 결재). 건별 모드는 기존 그대로.
    g.add_node(
        "loop_approvals",
        make_batch_approvals_node(allow_submit=allow_submit)
        if batch_limit
        else make_loop_approvals_node(on_popup=on_popup, allow_submit=allow_submit),
    )

    edges = [
        ("validate_params", "login"),
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "set_query"),
        ("set_query", "run_query"),
    ]
    if batch_limit:
        # run_query → count_details → loop_approvals(배치). ⚠ 카드(pre_loop_node)와는 배타 —
        # 카드는 결제창마다 행별 참조문서를 다루므로 묶음 결재와 양립하지 않는다.
        g.add_node("count_details", make_count_details_node(batch_limit))
        edges += [("run_query", "count_details"), ("count_details", "loop_approvals")]
    elif pre_loop_node is not None:
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


def build_voucher_by_type_graph():
    """유형별 전표조회 승인(voucher-by-type) — **배치 결재** + 상신 게이트 개방.

    외상매출금/외상매입금 병합(2026-08-20): 전표유형은 실행 전 폼 선택(state.docu_types,
    validate_params 산출)이 우선하고, 미지정이면 빌드 기본값(DOCU_TYPE_CHOICES 전체 3종)이다.
    메뉴(MENU_NM) 필터는 count_details 가 계획 단계에서 적용한다(state.menu_filters).
    배치 규율(2026-08-07 사용자 확정): 하위(계정정보) 200건 이상 전표는 단독으로 먼저,
    나머지는 합계가 200 미만이 되도록 묶어 결재창을 묶음당 1회 연다.
    """
    return build_voucher_graph(
        steps.DOCU_TYPE_CHOICES, batch_limit=DETAIL_BATCH_LIMIT, allow_submit=True
    )
