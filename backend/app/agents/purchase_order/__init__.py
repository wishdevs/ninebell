"""구매발주(purchase-order) 에이전트 패키지 — SCM-구매 3화면 파이프라인의 화면 ① 읽기 그래프.

Phase A: 프로젝트 선택(HITL search) → BOM 읽기 → 계획서(HITL planner) → 계획 확정 반환.
⚠ 저장(F7)·결재는 클릭하지 않는다 — 쓰기 경로는 실측 후 Phase B(PROCESS.md 남은 작업).
"""

from __future__ import annotations

from .graph import build_purchase_order_graph

__all__ = ["build_purchase_order_graph"]
