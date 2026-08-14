"""app.agents — 실 옴니솔 워크플로우 에이전트 패키지.

import 시 워크플로우를 엔진 레지스트리(app.live.registry)에 등록한다. main.py 가
`import app.agents` 한 줄로 등록을 트리거한다(demo-echo 는 app.live.registry 가 기본 등록).

컴파일된 LangGraph 는 stateless·재사용 가능 → 1회 컴파일 후 팩토리는 그걸 반환한다
(러너가 실행마다 새 state 를 ainvoke 로 주입).
"""

from __future__ import annotations

from app.live.registry import register_workflow

from .card_collect.graph import build_card_collect_graph
from .common.cleanup import build_doc_cleanup_graph
from .eap_cancel.graph import build_eap_cancel_graph
from .expense_card import build_expense_card_chat_graph
from .gyeongjo_grant.graph import GYEONGJO_GUBUN_LABEL, build_gyeongjo_grant_graph
from .hakjagum_grant.graph import HAKJAGUM_GUBUN_LABEL, build_hakjagum_grant_graph
from .purchase_order.graph import build_purchase_order_graph
from .trip_domestic.graph import TRIP_GUBUN_LABEL, build_trip_domestic_graph
from .trip_overseas.graph import TRIP_GUBUN_LABEL as TRIP_OVERSEAS_GUBUN_LABEL
from .trip_overseas.graph import build_trip_overseas_graph
from .voucher_card.graph import build_voucher_card_graph
from .voucher_receivable.graph import (
    build_voucher_payable_graph,
    build_voucher_receivable_graph,
)

# 1회 컴파일 후 재사용(demo_echo 등록 패턴과 동일).
_expense_card_chat_graph = build_expense_card_chat_graph()
register_workflow("expense-card-chat", lambda: _expense_card_chat_graph)

_card_collect_graph = build_card_collect_graph()
# delay_scale 0.15: 라이브 검증된 대기 배율(피커 실시간 상한 견고화 후 168s→~135s, 2026-07-04).
register_workflow("card-collect", lambda: _card_collect_graph, delay_scale=0.15)

_trip_domestic_graph = build_trip_domestic_graph()
# delay_scale 0.4: 대기(고정 settle·폴 간격)만 배율 축소 — 실 ERP 렌더/검색 시간은 불변이라
# 안전 여유를 둔 보수값(카드는 0.15 라이브검증, 트립은 캔버스 돋보기 피커가 트립 고유라 단계적
# 하향). 상한(피커 안정 폴 cap)은 유지돼 서버 재조회 보장은 그대로. 런타임 튜닝은 env
# CARD_DELAY_SCALE 이 우선(0.15 까지 낮춰보고 10사이클 실저장 무결 확인 후 코드 기본값 하향).
register_workflow("trip-domestic", lambda: _trip_domestic_graph, delay_scale=0.4)

_trip_overseas_graph = build_trip_overseas_graph()
# 국내/자차와 동일 플로우·프리미티브 재사용 → 같은 delay_scale(0.4). env CARD_DELAY_SCALE 우선.
register_workflow("trip-overseas", lambda: _trip_overseas_graph, delay_scale=0.4)

# 테스트 문서 정리(디버그, 사용자 요청 2026-08-10 → 결의서 전체 확대) — 스모크 삭제 가드레일
# 이식(공용 cleanup). hidden 픽스처라 목록/상세 비노출, 실행은 관리자 + 디버그 모드 버튼 전용.
# 라벨·FG 코드는 각 그래프 상수 + e2e 스모크 삭제 가드 실측값(워크플로우 교차검증 2026-08-10:
# 카드 52 · 국내출장 53 · 해외출장 54 · 경조금 55 · 학자금 56).
for _cid, _label, _fg in (
    ("trip-domestic-cleanup", TRIP_GUBUN_LABEL, "53"),
    ("trip-overseas-cleanup", TRIP_OVERSEAS_GUBUN_LABEL, "54"),
    ("card-collect-cleanup", "카드", "52"),  # card_collect/graph.py:77 리터럴과 동일.
    ("gyeongjo-grant-cleanup", GYEONGJO_GUBUN_LABEL, "55"),
    ("hakjagum-grant-cleanup", HAKJAGUM_GUBUN_LABEL, "56"),
):
    _cleanup_graph = build_doc_cleanup_graph(_label, _fg)
    register_workflow(_cid, (lambda g: (lambda: g))(_cleanup_graph), delay_scale=0.4)

_eap_cancel_graph = build_eap_cancel_graph()
# 전자결재 상신 취소(디버그, 사용자 요청 2026-08-12) — voucher 3종이 실제 상신한 문서를
# 회수하는 경로. e2e/eap_approval_cancel_probe.py 를 프로덕션 그래프로 이식했다.
# ⚠ delay_scale 을 주지 않는다(=1.0, 무배율). 취소 3단계는 비가역이고, 프로브가 PASS 한
# 타이밍이 실시간 그대로였다 — 검증된 타이밍에서 벗어날 이득이 없다.
register_workflow("eap-approval-cancel", lambda: _eap_cancel_graph)

_gyeongjo_grant_graph = build_gyeongjo_grant_graph()
# 국내/해외출장과 동일 detail 스키마·프리미티브 재사용(단건) → 같은 delay_scale(0.4). env 우선.
register_workflow("gyeongjo-grant", lambda: _gyeongjo_grant_graph, delay_scale=0.4)

_hakjagum_grant_graph = build_hakjagum_grant_graph()
# 경조금 형제 클론(동일 detail 스키마·프리미티브 재사용, 단건) → 같은 delay_scale(0.4). env 우선.
register_workflow("hakjagum-grant", lambda: _hakjagum_grant_graph, delay_scale=0.4)

_purchase_order_graph = build_purchase_order_graph()
# 구매발주 Phase A(읽기+계획서 HITL, 2026-08-13) — 저장(F7)·결재 없음(계획 확정까지).
# delay_scale 0.4: 진입·도움창·조회 사이클을 검증한 읽기 프로브가 전부 0.4 로 PASS 한 배율.
register_workflow("purchase-order", lambda: _purchase_order_graph, delay_scale=0.4)

_voucher_receivable_graph = build_voucher_receivable_graph()
# delay_scale 0.4: 헤드리스 프로브(2026-07-20~21, 단건·3건 배치 그린)가 검증한 대기 배율.
# 조회+결재(결제창=별도 팝업 Page) 아키타입. ⚠ 실제 상신 실행(allow_submit 개방, 사용자 승인
# 2026-08-07 — EAP 결재취소 e2e 로 회수 가능) · 보관 미클릭 · 전체 진행.
register_workflow("voucher-receivable", lambda: _voucher_receivable_graph, delay_scale=0.4)

# 외상매입금 — 외상매출금과 전부 공유하고 전표유형만 내수구매(build_voucher_graph 재사용).
_voucher_payable_graph = build_voucher_payable_graph()
register_workflow("voucher-payable", lambda: _voucher_payable_graph, delay_scale=0.4)

# 미지급금 법인카드 — 공유 백본(전표조회승인 조회+결재) + 카드 3대 확장(결의서조회승인 결재번호
# 수집 · 참조문서 선택 훅). ⚠ 참조문서 확인·실제 상신 모두 실행(2026-08-07 게이트 개방).
_voucher_card_graph = build_voucher_card_graph()
register_workflow("voucher-card", lambda: _voucher_card_graph, delay_scale=0.4)

__all__ = [
    "build_card_collect_graph",
    "build_eap_cancel_graph",
    "build_expense_card_chat_graph",
    "build_gyeongjo_grant_graph",
    "build_hakjagum_grant_graph",
    "build_purchase_order_graph",
    "build_trip_domestic_graph",
    "build_trip_overseas_graph",
    "build_voucher_card_graph",
    "build_voucher_payable_graph",
    "build_voucher_receivable_graph",
]
