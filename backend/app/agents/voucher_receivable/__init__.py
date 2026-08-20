"""전표조회승인(voucher-by-type) 에이전트 패키지 — 조회+결재 아키타입.

외상매출금/외상매입금을 '유형별 전표조회 승인' 하나로 병합했다(2026-08-20) — 전표유형은
실행 전 폼의 다중 선택(국내매출/해외매출/내수구매). ⚠ 상신은 allow_submit 게이트 뒤에서만
실클릭한다(정책 전환 2026-08-07) — 보관은 절대 미클릭, 저장·삭제 없음.
"""

from __future__ import annotations

from .graph import build_voucher_by_type_graph

__all__ = ["build_voucher_by_type_graph"]
