"""전표조회승인(voucher-receivable) 에이전트 패키지 — 조회+결재 아키타입.

⚠ 실제 상신·저장·삭제 없음. 결제창을 열어 '가상 상신' 로그만 남기고 닫는다(비영속).
"""

from __future__ import annotations

from .graph import build_voucher_receivable_graph

__all__ = ["build_voucher_receivable_graph"]
