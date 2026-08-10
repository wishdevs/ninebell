"""미지급금 법인카드(voucher-card) — LangGraph StateGraph 조립.

공유 백본(voucher_receivable.build_voucher_graph: 전표조회승인 조회+결재)을 그대로 재사용하고
카드 고유 확장 3가지를 훅으로 얹는다:
  - 전표유형=일반(SYSDEF_CD=11)로 공유 set_query 재사용(대상=결의구분=카드·ABDOCU_NO 있는 행).
  - validate: 회계일 기간 파싱(공유 max_rows + period_from~period_to).
  - pre_loop_node = collect_payments: 결의서조회승인 다중탭 → 결의구분=카드 일괄 조회 →
    ABDOCU_NO→GWDOCU_NO 맵 수집(state.payment_map).
  - on_popup = reference_doc: 결제창 안 참조문서 선택(문서번호=이 행 GWDOCU_NO) + 확인 클릭
    (allow_confirm 게이트 개방) + 첨부 1건 검증.

체인: validate_params → login → user_type(회계) → menu_nav(전표조회승인) → set_query(일반)
      → run_query → collect_payments → loop_approvals(on_popup=참조문서) → END.

⚠ 안전(정책 전환 2026-08-07): 참조문서 확인·상신 모두 게이트 개방 — 참조문서 첨부 검증 통과 후
  상신까지 실클릭한다(allow_submit=True, EAP 취소 e2e 로 가역). 보관은 여전히 절대 미클릭.
"""

from __future__ import annotations

from app.agents.voucher_receivable.graph import VoucherReceivableState, build_voucher_graph

from . import steps
from .nodes import (
    make_collect_payments_node,
    make_reference_doc_hook,
    make_validate_params_node,
)


class VoucherCardState(VoucherReceivableState, total=False):
    """공유 State(max_rows/master_rowcount/processed…) 상속 + 카드 고유 키 선언.

    ⚠ 노드 반환 키는 전부 여기(또는 상속)에 선언돼야 다음 노드로 전달된다(LangGraph silent drop).
    """

    payment_map: dict[str, str]  # collect_payments — ABDOCU_NO→GWDOCU_NO(결재번호) 맵
    payment_map_count: int  # 수집 매핑 건수(진단)


def build_voucher_card_graph():
    """미지급금 법인카드 조회+결재+참조문서 체인을 컴파일해 반환(stateless·재사용)."""
    return build_voucher_graph(
        steps.DOCU_TYPES_CARD,  # 전표유형 = 일반
        state_cls=VoucherCardState,
        validate_node=make_validate_params_node(),
        pre_loop_node=make_collect_payments_node(),
        # 게이트 개방(사용자 확정 2026-08-07): 선택 1건 확인 → **확인 클릭** → 결제창 '참조문서'
        # 필드 첨부 1건 검증까지 통과해야 그 결제건 완료. 검증 통과 후 **상신까지 실클릭**
        # (allow_submit — 같은 날 정책 전환, EAP 취소 e2e 로 가역). 보관은 여전히 절대 미클릭.
        on_popup=make_reference_doc_hook(allow_confirm=True),
        allow_submit=True,
    )
