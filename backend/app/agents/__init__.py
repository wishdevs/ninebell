"""app.agents — 실 옴니솔 워크플로우 에이전트 패키지.

import 시 워크플로우를 엔진 레지스트리(app.live.registry)에 등록한다. main.py 가
`import app.agents` 한 줄로 등록을 트리거한다(demo-echo 는 app.live.registry 가 기본 등록).

컴파일된 LangGraph 는 stateless·재사용 가능 → 1회 컴파일 후 팩토리는 그걸 반환한다
(러너가 실행마다 새 state 를 ainvoke 로 주입).
"""

from __future__ import annotations

from app.live.registry import register_workflow

from .card_collect.graph import build_card_collect_graph
from .expense_card import build_expense_card_chat_graph
from .gyeongjo_grant.graph import build_gyeongjo_grant_graph
from .hakjagum_grant.graph import build_hakjagum_grant_graph
from .trip_domestic.graph import build_trip_domestic_graph
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

_gyeongjo_grant_graph = build_gyeongjo_grant_graph()
# 국내/해외출장과 동일 detail 스키마·프리미티브 재사용(단건) → 같은 delay_scale(0.4). env 우선.
register_workflow("gyeongjo-grant", lambda: _gyeongjo_grant_graph, delay_scale=0.4)

_hakjagum_grant_graph = build_hakjagum_grant_graph()
# 경조금 형제 클론(동일 detail 스키마·프리미티브 재사용, 단건) → 같은 delay_scale(0.4). env 우선.
register_workflow("hakjagum-grant", lambda: _hakjagum_grant_graph, delay_scale=0.4)

_voucher_receivable_graph = build_voucher_receivable_graph()
# delay_scale 0.4: 헤드리스 프로브(2026-07-20~21, 단건·3건 배치 그린)가 검증한 대기 배율.
# 조회+결재(결제창=별도 팝업 Page) 아키타입. ⚠ 실제 상신 없음(가상 상신 로그만) · 전체 진행.
register_workflow("voucher-receivable", lambda: _voucher_receivable_graph, delay_scale=0.4)

# 외상매입금 — 외상매출금과 전부 공유하고 전표유형만 내수구매(build_voucher_graph 재사용).
_voucher_payable_graph = build_voucher_payable_graph()
register_workflow("voucher-payable", lambda: _voucher_payable_graph, delay_scale=0.4)

# 미지급금 법인카드 — 공유 백본(전표조회승인 조회+결재) + 카드 3대 확장(결의서조회승인 결재번호
# 수집 · 참조문서 선택 훅). ⚠ 실제 상신·참조문서 확인 없음(가상 상신 로그만).
_voucher_card_graph = build_voucher_card_graph()
register_workflow("voucher-card", lambda: _voucher_card_graph, delay_scale=0.4)

__all__ = [
    "build_card_collect_graph",
    "build_expense_card_chat_graph",
    "build_gyeongjo_grant_graph",
    "build_hakjagum_grant_graph",
    "build_trip_domestic_graph",
    "build_trip_overseas_graph",
    "build_voucher_card_graph",
    "build_voucher_payable_graph",
    "build_voucher_receivable_graph",
]
